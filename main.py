import os
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel                       # <-- MAKE SURE THIS LINE IS PRESENT
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client

# Explicitly load the local .env variables at runtime booting
load_dotenv()

app = FastAPI(title="Kapas Ki Sehat - Walking Skeleton Backend")
# ... (Keep your CORS middleware configuration block exactly here) ...

# =====================================================================
# SECURE SUPABASE CLIENT INITIALIZATION
# =====================================================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[CRITICAL WARNING] Missing environment configuration variables inside your .env configuration bundle!")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# =====================================================================
# Pydantic Schemas
# =====================================================================
class SupabaseWebhookPayload(BaseModel):
    type: Optional[str] = "INSERT"
    table: Optional[str] = "diagnostic_logs"
    schema_name: Optional[str] = "public"
    record: Dict[str, Any]
    old_record: Optional[Dict[str, Any]] = None

# =====================================================================
# Asynchronous Background Tasks (The Stub ML Model Loop)
# =====================================================================
async def run_gatekeeper_verification(record: dict):
    row_id = record.get('id')
    print(f"\n[MLOPS EVENT] Waking background thread worker for row ID: {row_id}")
    
    # 1. SIMULATE STUB ML MODEL PROCESSING DELAY
    # Tweaking parameters to mimic a small edge network evaluation pass
    await asyncio.sleep(2.0)
    
    # 2. RUN LIGHTWEIGHT STUB MODEL EVALUATION
    # Generating standard deterministic outputs to simulate model inferences safely
    simulated_confidence = 0.84
    simulated_pest = "Whitefly Nymphs Detected"
    simulated_risk = "CRITICAL"
    
    print(f"[MLOPS EVENT] Stub Model processing complete. Writing analytical inferences back to cloud repository...")

    try:
        # 3. LIVE DATABASE WRITE-BACK STEP
        # This targets the exact row ID that triggered the webhook and fills the metrics
        response = supabase_client.table("diagnostic_logs").update({
            "confidence_score": simulated_confidence,
            "risk_level": simulated_risk,
            "detected_anomaly": simulated_pest # If your schema requires this, or map to whitefly_count
        }).eq("id", row_id).execute()
        
        print(f"[MLOPS EVENT] Database sync state updated successfully for ID: {row_id}!\n")
        
    except Exception as e:
        print(f"[CRITICAL ERR] Write-back transaction failed to push downstream: {str(e)}\n")

# =====================================================================
# API Endpoints & Webhooks
# =====================================================================
@app.get("/")
def read_root():
    return {"status": "online", "message": "Kapas Ki Sehat API is fully operational Core Sandbox"}

@app.post("/api/v1/supabase-webhook")
async def handle_supabase_webhook(payload: SupabaseWebhookPayload, background_tasks: BackgroundTasks):
    if payload.type == "INSERT" and payload.table == "diagnostic_logs":
        confidence = float(payload.record.get("confidence_score", 1.0))
        # If confidence is low, hand it off to our asynchronous Stub ML worker background thread
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

# 2. THE IMAGE SCAN & INFERENCE ENDPOINT
@app.post("/api/v1/scan")
async def process_crop_scan(file: UploadFile = File(...)):
    contents = await file.read()
    await asyncio.sleep(1.5)
    return {
        "status": "success",
        "filename": file.filename,
        "detection_found": True,
        "pest_type": "Whitefly",
        "confidence": 0.89,
        "recommendation_ur": "سفید مکھی کا حملہ واضح ہے۔ فصل پر فوری تجویز کردہ سپرے کریں۔"
    }

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