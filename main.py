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

# Ensure emoji print() calls don't crash on Windows cp1252 consoles
import sys
sys.stdout.reconfigure(encoding="utf-8")

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

# Optional service-role key for downloading from private Storage buckets.
# If unset, falls back to the anon key (works for public buckets only).
# Set SUPABASE_SERVICE_KEY in .env once you create the leaf-images bucket.
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[CRITICAL WARNING] Missing environment configuration variables inside your .env configuration bundle!")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Dedicated client for Storage reads — uses service-role key when available
# so the gatekeeper can download from a private bucket. Anon key is the fallback.
_storage_client: Client = (
    create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    if SUPABASE_SERVICE_KEY
    else supabase_client
)


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

    return _storage_client.storage.from_(STORAGE_BUCKET).download(path)

# =====================================================================
# Pydantic Schemas
# =====================================================================
class ChatRequest(BaseModel):
    message: str
    language: str = "ur"    # canonical language code (§5): ur | pa | skr | en

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


def estimate_whitefly_count(predicted_class: str, confidence: float) -> int:
    """Derive a representative whitefly count from classifier output (Option B).

    The model is a classifier — it cannot count insects. This function maps
    (predicted_class, confidence) to a count value that, when passed through
    derive_risk_level(), produces an appropriate severity band.

    Mapping (see CONTRACTS.md §11):
      Fresh_Leaf (any confidence) → 0  → LOW
      Pest, confidence >= 0.90   → 18 → CRITICAL
      Pest, confidence >= 0.75   → 12 → HIGH
      Pest, confidence >= 0.50   → 6  → MEDIUM
      Pest, confidence <  0.50   → 3  → LOW  (weak/ambiguous detection)

    Replace with a real counting model (Option A) when one is available.
    """
    if predicted_class == "Fresh_Leaf":
        return 0
    if confidence >= 0.90:
        return 18   # CRITICAL band (16+)
    if confidence >= 0.75:
        return 12   # HIGH band (9–15)
    if confidence >= 0.50:
        return 6    # MEDIUM band (5–8)
    return 3        # LOW band (0–4) — weak/ambiguous detection

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
# Returns canonical numeric fields + risk_level enum (§3.3, §4).
# Values are stubs until this endpoint is wired to real weather/telemetry data.
@app.get("/api/v1/risk-metrics")
def get_risk_metrics(district: str = "Multan"):
    return {
        "district": district.upper(),
        "temperature": 37.0,          # °C — stub
        "humidity": 42.0,             # % — stub
        "wind_speed": 14.0,           # km/h — stub
        "risk_level": "CRITICAL",     # canonical enum (§4) — stub
        "alert_text_en": "High risk of Whitefly expansion due to continuous dry heat wave.",
        "alert_text_ur": "سنگین خطرہ: مسلسل خشک گرمی کی وجہ سے سفید مکھی کا پھیلاؤ کا زیادہ خطرہ۔"
    }

# =====================================================================
# MOBILE PHONE SCAN INFERENCE ENDPOINT (WITH GPS TELEMETRY)
# =====================================================================
@app.post("/api/v1/scan")
async def process_crop_scan(
    file: UploadFile = File(...),
    latitude: Optional[float] = Form(None),  # null when GPS unavailable — NOT 0.0 (§3.1)
    longitude: Optional[float] = Form(None)  # null when GPS unavailable — NOT 0.0 (§3.1)
):
    try:
        # 1. Read the incoming byte stream from the phone app
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert("RGB")

        # 2. Run image through the live PyTorch inference pipeline
        tensor = inference_transforms(image).unsqueeze(0).to(DEVICE)

        with torch.no_grad():
            outputs = model(tensor)
            probabilities = torch.nn.functional.softmax(outputs[0], dim=0)
            top_prob, top_idx = torch.max(probabilities, dim=0)

        confidence = float(top_prob.item())
        prediction = CLASSES[top_idx.item()]

        # [W1] Derive whitefly_count from (class, confidence) via Option B.
        # estimate_whitefly_count() maps to a representative count so that
        # derive_risk_level() produces a meaningful severity band.
        count = estimate_whitefly_count(prediction, confidence)

        # Canonical recommendations (§7). pa/skr are TEMPORARY placeholders
        # (Urdu string) pending verified native translations — see CONTRACTS.md §7.
        if prediction != "Fresh_Leaf":
            action_en = "Apply targeted mitigation spray in morning or evening."
            action_ur = "سفید مکھی کے تدارک کے لیے متعلقہ اسپرے صبح یا شام کے وقت کریں۔"
            # TODO: replace with verified PA/SKR translation — placeholder is Urdu
            action_pa = action_ur
            # TODO: replace with verified PA/SKR translation — placeholder is Urdu
            action_skr = action_ur
            pest_type = "Whitefly"
        else:
            action_en = "Crop is healthy. No spray required."
            action_ur = "کپاس کی فصل صحت مند ہے۔ کسی اسپرے کی ضرورت نہیں ہے۔"
            # TODO: replace with verified PA/SKR translation — placeholder is Urdu
            action_pa = action_ur
            # TODO: replace with verified PA/SKR translation — placeholder is Urdu
            action_skr = action_ur
            pest_type = "None"

        print(f"📡 [SCAN COMPUTED] Lat: {latitude}, Lon: {longitude} | {prediction} | conf={confidence:.2f} count={count}")

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
            "recommendation_pa": action_pa,    # ⚠️ placeholder = Urdu (§7)
            "recommendation_skr": action_skr,  # ⚠️ placeholder = Urdu (§7)
            "latitude": latitude,
            "longitude": longitude
        }
    except Exception as e:
        print(f"❌ [SCAN API CRASH] {str(e)}")
        return {"status": "error", "message": str(e)}

# 3. THE LEVEL 1 SUPPORT CHATBOT ENDPOINT
# Accepts a JSON body (§3.4): {"message": "...", "language": "ur"}
@app.post("/api/v1/chat")
async def chatbot_triage(body: ChatRequest):
    await asyncio.sleep(0.5)
    clean_msg = body.message.strip()
    if "مکھی" in clean_msg or "سفید" in clean_msg:
        reply = "سفید مکھی کے تدارک کے لیے محکمہ زراعت کی تجویز کردہ کیمیکلز کا سپرے صبح یا شام کے وقت کریں۔"
    elif "پانی" in clean_msg or "آبپاشی" in clean_msg:
        reply = "شدید گرمی کی لہر کے دوران کپاس کی فصل کو ہلکا پانی لگائیں، تا کہ نمی برقرار رہے ۔"
    else:
        reply = "آپ کا سوال موصول ہو گیا ہے۔ ہماری معلوماتی ڈیٹا بیس کے مطابق کپاس کی صحت برقرار رکھنے کے لیے باقاعدہ معائنہ ضروری ہے۔"
    return {"reply": reply}