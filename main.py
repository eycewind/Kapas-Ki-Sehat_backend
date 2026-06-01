import os
import io
import torch
import torchvision.transforms as transforms
from PIL import Image
from torchvision.models import mobilenet_v2, MobileNet_V2_Weights
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict    # <-- MAKE SURE THIS LINE IS PRESENT
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client

# Explicitly load the local .env variables at runtime booting
load_dotenv()

app = FastAPI(title="Kapas Ki Sehat - Walking Skeleton Backend")

# CORS — the Next.js dashboard calls this API from the browser.
# Permissive for local/dev; tighten allow_origins to the dashboard origin(s)
# (e.g. via a CORS_ALLOW_ORIGINS env var) before production.
_cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",")] if _cors_origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# LIVE PYTORCH MODEL INITIALIZATION
# =====================================================================
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CLASSES = ['Fresh_Leaf', 'Leaf_Reddening', 'Leaf_Spot_Bacterial_Blight', 'Yellowish_Leaf']

# Reconstruct the exact same network structure Antigravity defined
model = mobilenet_v2(weights=None)
model.classifier[1] = torch.nn.Linear(model.last_channel, len(CLASSES))

# Load the weights you just trained on your RTX 4060.
# Path comes from .env (MODEL_PATH) so it isn't tied to one machine.
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join("models", "cottonace_stub.pth"))
if os.path.exists(MODEL_PATH):
    # 1. Read the full metadata dictionary from the file
    checkpoint = torch.load(MODEL_PATH, map_location=DEVICE)
    
    # 2. Defensive check: Extract the inner state_dict if it's wrapped
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
    else:
        model.load_state_dict(checkpoint) # Fallback if it was just pure weights
        
    print(f"🚀 Success: Loaded live custom weights from {MODEL_PATH}")
else:
    print(f"⚠️ Warning: {MODEL_PATH} not found. Running un-trained fallback weights.")

model.to(DEVICE)
model.eval()

# Standard image processing pipeline matching your training data
inference_transforms = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

# =====================================================================
# SECURE SUPABASE CLIENT INITIALIZATION
# =====================================================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Storage bucket that holds the leaf images referenced by diagnostic_logs.image_storage_path.
# Override in .env if your bucket is named differently.
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "leaf-images")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[CRITICAL WARNING] Missing environment configuration variables inside your .env configuration bundle!")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def download_leaf_image(storage_path: str) -> bytes:
    """Fetch raw image bytes from Supabase Storage for a diagnostic_logs row.

    Tolerates three shapes the mobile app might store in image_storage_path:
      - a bare object key:            "uploads/abc.jpg"
      - a key prefixed with bucket:   "leaf-images/uploads/abc.jpg"
      - a full public/signed URL:     "https://.../object/public/leaf-images/uploads/abc.jpg"
    """
    path = (storage_path or "").strip()

    if path.startswith("http"):
        marker = f"/{STORAGE_BUCKET}/"
        if marker in path:
            path = path.split(marker, 1)[1]
        # strip any signed-URL query string
        path = path.split("?", 1)[0]
    elif path.startswith(f"{STORAGE_BUCKET}/"):
        path = path[len(STORAGE_BUCKET) + 1:]

    return supabase_client.storage.from_(STORAGE_BUCKET).download(path)

# =====================================================================
# Pydantic Schemas
# =====================================================================
class SupabaseWebhookPayload(BaseModel):
    # Supabase sends the key "schema" (not "schema_name"); alias maps it.
    # populate_by_name lets either spelling parse, for resilience.
    model_config = ConfigDict(populate_by_name=True)

    type: Optional[str] = "INSERT"
    table: Optional[str] = "diagnostic_logs"
    schema_name: Optional[str] = Field(default="public", alias="schema")
    record: Dict[str, Any]
    old_record: Optional[Dict[str, Any]] = None

# =====================================================================
# CANONICAL RISK LEVEL (see CONTRACTS.md §4)
# =====================================================================
def derive_risk_level(whitefly_count) -> str:
    """Map whitefly_count → canonical risk_level band (LOW/MEDIUM/HIGH/CRITICAL)."""
    try:
        count = int(whitefly_count)
    except (TypeError, ValueError):
        return "LOW"
    if count >= 16:
        return "CRITICAL"
    if count >= 9:
        return "HIGH"
    if count >= 5:
        return "MEDIUM"
    return "LOW"

# =====================================================================
# ASYNCHRONOUS HIGH-FIDELITY TRIAGE WORKER
# =====================================================================
async def run_gatekeeper_verification(record: dict):
    row_id = record.get("id")
    image_storage_path = record.get("image_storage_path") # Path within the Supabase storage bucket (actual column name)
    
    print(f"[MLOPS LIVE] Executing deep high-fidelity verification pass for row ID: {row_id}")

    # Without the actual leaf image there is nothing to verify. Bail out rather
    # than fabricate a result over the farmer's real edge-device values.
    if not image_storage_path:
        print(f"⚠️ [MLOPS SKIP] Row {row_id} has no image_storage_path; leaving edge values untouched.")
        return

    try:
        # 1. Pull the real leaf image the farmer uploaded and run it through the model
        image_bytes = download_leaf_image(image_storage_path)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = inference_transforms(image).unsqueeze(0).to(DEVICE)

        with torch.no_grad():
            outputs = model(tensor)
            probabilities = torch.nn.functional.softmax(outputs[0], dim=0)
            top_prob, top_idx = torch.max(probabilities, dim=0)

        final_confidence = float(top_prob.item())
        predicted_class = CLASSES[top_idx.item()]

        # Canonical risk_level (§4): a healthy leaf is LOW; otherwise severity
        # scales with whitefly_count using the canonical bands.
        # NOTE: the image model is a classifier and does not itself count
        # whiteflies, so risk is derived from record["whitefly_count"].
        # (Nuance flagged for the next MASTER-CONTRACTS refresh.)
        if predicted_class == "Fresh_Leaf":
            derived_risk = "LOW"
        else:
            derived_risk = derive_risk_level(record.get("whitefly_count"))

        # 2. Write the higher-fidelity result back to the diagnostic_logs row.
        # NOTE: diagnostic_logs has no `status` column — writing one raises
        # PGRST204 and (because of the except below) silently drops the whole
        # update. Only write columns that actually exist in the schema.
        supabase_client.table("diagnostic_logs").update({
            "confidence_score": round(final_confidence, 2),
            "risk_level": derived_risk
        }).eq("id", row_id).execute()
        
        print(f"✅ [DATABASE SYNC SUCCESS] Row {row_id} mapped to {predicted_class} with {final_confidence:.2f} confidence.")
        
    except Exception as e:
        print(f"❌ [MLOPS CRASH] Verification pipeline loop failed: {str(e)}")

# =====================================================================
# API Endpoints & Webhooks
# =====================================================================
@app.get("/")
def read_root():
    return {"status": "online", "message": "Kapas Ki Sehat API is fully operational Core Sandbox"}

# Place this global set right above your endpoints
processed_webhook_ids = set()

@app.post("/api/v1/supabase-webhook")
async def handle_supabase_webhook(payload: SupabaseWebhookPayload, background_tasks: BackgroundTasks):
    if payload.type == "INSERT" and payload.table == "diagnostic_logs":
        row_id = payload.record.get("id")
        
        # Defensive Check: If this exact row ID is already being handled, drop the duplicate duplicate
        if row_id in processed_webhook_ids:
            return {"status": "ignored", "message": "Duplicate event transaction already processing"}
            
        # Register the ID in memory
        processed_webhook_ids.add(row_id)
        
        confidence = float(payload.record.get("confidence_score", 1.0))
        if confidence < 0.75:
            background_tasks.add_task(run_gatekeeper_verification, payload.record)
            
    return {"status": "accepted", "message": "Payload queued for system execution processing"}

# 1. THE DISTRICT RISK UPDATE ENDPOINT
@app.get("/api/v1/risk-metrics")
def get_risk_metrics(district: str = "Multan"):
    return {
        "district": district.upper(),
        "temperature": "37°C",
        "humidity": "42%",
        "wind_speed": "14 km/h",
        "risk_level": "CRITICAL WHITEFLY RISK",
        "alert_text_en": "High risk of Whitefly expansion due to continuous dry heat wave.",
        "alert_text_ur": "سنگین خطرہ: مسلسل خشک گرمی کی وجہ سے سفید مکھی کا پھیلاؤ کا زیادہ خطرہ۔"
    }

# =====================================================================
# MOBILE PHONE SCAN INFERENCE ENDPOINT (WITH GPS TELEMETRY)
# =====================================================================
@app.post("/api/v1/scan")
async def process_crop_scan(
    file: UploadFile = File(...),
    latitude: Optional[float] = Form(0.0),   # Catch incoming GPS lat coordinates
    longitude: Optional[float] = Form(0.0)   # Catch incoming GPS lon coordinates
):
    try:
        # 1. Read the incoming byte stream from your phone app
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert("RGB")
        
        # 2. Run image through your live PyTorch tensor transformation array
        tensor = inference_transforms(image).unsqueeze(0).to(DEVICE)
        
        with torch.no_grad():
            outputs = model(tensor)
            probabilities = torch.nn.functional.softmax(outputs[0], dim=0)
            top_prob, top_idx = torch.max(probabilities, dim=0)
            
        confidence = float(top_prob.item())
        prediction = CLASSES[top_idx.item()]
        
        # Determine notification messaging based on target evaluation
        if prediction != "Fresh_Leaf":
            action_en = "Apply targeted mitigation if pest status is confirmed."
            action_ur = "سفید مکھی کے تدارک کے لیے متعلقہ اسپرے صبح یا شام کے وقت کریں۔"
            pest_type = "Whitefly"
            count = 12
        else:
            action_en = "Crop healthy."
            action_ur = "کپاس کی فصل صحت مند ہے۔ کسی اسپرے کی ضرورت نہیں ہے۔"
            pest_type = "None"
            count = 0

        print(f"📡 [SCAN COMPUTED] Lat: {latitude}, Lon: {longitude} | Result: {prediction}")

        # Note: When Antigravity updates your app to run the initial database INSERT, 
        # these fields (latitude, longitude) will be included in that step, allowing 
        # your background webhook to pass them right along to your triage worker!

        return {
            "status": "success",
            "prediction": prediction,
            "confidence": round(confidence, 2),
            "confidence_score": round(confidence, 2),
            "pest_type": pest_type,
            "whitefly_count": count,
            "action_protocol": action_en,
            "recommendation_en": action_en,
            "recommendation_ur": action_ur,
            
            # Echo back coordinates to client for validation
            "latitude": latitude,
            "longitude": longitude
        }
    except Exception as e:
        print(f"❌ [SCAN API CRASH] {str(e)}")
        return {"status": "error", "message": str(e)}

# 3. THE LEVEL 1 SUPPORT CHATBOT ENDPOINT
@app.post("/api/v1/chat")
async def chatbot_triage(message: str = Form(...), language: str = Form("ur")):
    await asyncio.sleep(0.5)
    clean_msg = message.strip()
    if "مکھی" in clean_msg or "سفید" in clean_msg:
        reply = "سفید مکھی کے تدارک کے لیے محکمہ زراعت کی تجویز کردہ کیمیکلز کا سپرے صبح یا شام کے وقت کریں۔"
    elif "پانی" in clean_msg or "آبپاشی" in clean_msg:
        reply = "شدید گرمی کی لہر کے دوران کپاس کی فصل کو ہلکا پانی لگائیں، تا کہ نمی برقرار رہے ۔"
    else:
        reply = "آپ کا سوال موصول ہو گیا ہے۔ ہماری معلوماتی ڈیٹا بیس کے مطابق کپاس کی صحت برقرار رکھنے کے لیے باقاعدہ معائنہ ضروری ہے۔"
    return {"reply": reply}