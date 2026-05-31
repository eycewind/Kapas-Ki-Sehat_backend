from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
import asyncio

app = FastAPI(title="Kapas Ki Sehat - Walking Skeleton Backend")

# Enable CORS so your local physical phone can securely talk to your computer's IP
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# Pydantic Schemas
# =====================================================================
class SupabaseWebhookPayload(BaseModel):
    type: Optional[str] = "INSERT"                    # Default fallback
    table: Optional[str] = "diagnostic_logs"           # Default fallback
    schema_name: Optional[str] = "public"
    record: Dict[str, Any]                             # The raw database row row object
    old_record: Optional[Dict[str, Any]] = None

# =====================================================================
# Asynchronous Background Tasks
# =====================================================================
async def run_gatekeeper_verification(record: dict):
    print(f"\n[MLOPS EVENT] Low confidence alert detected. Initializing Gatekeeper data harvesting loop for row ID: {record.get('id')}\n")
    # Google AI Studio / Gemini API validation sequence to be appended here

# =====================================================================
# API Endpoints & Webhooks
# =====================================================================

@app.get("/")
def read_root():
    return {"status": "online", "message": "Kapas Ki Sehat API is fully operational Core Sandbox"}

# NEW: Event-Driven Supabase Webhook Receiver
@app.post("/api/v1/supabase-webhook")
async def handle_supabase_webhook(payload: SupabaseWebhookPayload, background_tasks: BackgroundTasks):
    if payload.type == "INSERT" and payload.table == "diagnostic_logs":
        confidence = float(payload.record.get("confidence_score", 1.0))
        if confidence < 0.75:
            background_tasks.add_task(run_gatekeeper_verification, payload.record)
    return {"status": "accepted", "message": "Payload queued for system execution processing"}

# 1. THE DISTRICT RISK UPDATE ENDPOINT
@app.get("/api/v1/risk-metrics")
def get_risk_metrics(district: str = "Multan"):
    # Simulating a live database read for the district dashboard metrics
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
    # Read the file data into memory to simulate local network load
    contents = await file.read()
    
    # Simulate hardware/ML inference delay (1.5 seconds) so your app loading spinner works realistically
    await asyncio.sleep(1.5)
    
    # Return a mock payload mirroring what the final computer vision model will output
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
    
    # Basic structural interceptor mimicking primitive matching logic
    clean_msg = message.strip()
    if "مکھی" in clean_msg or "سفید" in clean_msg:
        reply = "سفید مکھی کے تدارک کے لیے محکمہ زراعت کی تجویز کردہ کیمیکلز کا سپرے صبح یا شام کے وقت کریں۔"
    elif "پانی" in clean_msg or "آبپاشی" in clean_msg:
        reply = "شدید گرمی کی لہر کے دوران کپاس کی فصل کو ہلکا پانی لگائیں، تا کہ نمی برقرار رہے ۔"
    else:
        reply = "آپ کا سوال موصول ہو گیا ہے۔ ہماری معلوماتی ڈیٹا بیس کے مطابق کپاس کی صحت برقرار رکھنے کے لیے باقاعدہ معائنہ ضروری ہے۔"
        
    return {"reply": reply}