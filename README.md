# Kapas Ki Sehat (CottonAce) - Backend Core Engine 🌾🛡️

An event-driven, asynchronous MLOps backend architecture designed for the early detection and triage of Whitefly infestations in cotton crops across Pakistan's agricultural belts. This repository serves as the "Walking Skeleton" infrastructure, bridging mobile telemetry data, cloud storage schemas, and local automated machine learning validation handlers.

---

## 🏗️ Architectural Overview

The engine operates on a reactive, event-driven loop to process field diagnostics without blocking client-side mobile execution:

1. Telemetry Ingestion: Mobile devices insert diagnostic telemetry (leaf imagery paths, coordinates, and edge device confidence scores) into a remote Supabase PostgreSQL instance.
2. Webhooks Edge Trigger: A strict database constraint trigger monitors inserts on the logging schema and immediately fires an HTTP POST payload over an active ngrok reverse-proxy tunnel to this local engine.
3. Asynchronous Triage Worker: If the edge model's confidence falls below an established operational threshold (< 0.75), FastAPI intercepts the payload and provisions an isolated background task.
4. Closed-Loop Synchronization: The background worker runs an analytical stub evaluation pass (mimicking higher-fidelity validation models) and automatically updates the database row state, updating the Next.js administration dashboard in real time.

---

## 🛠️ System Pre-requisites & Stack

* Runtime Environment: Python 3.10+ managed via Anaconda/Conda.
* Core Framework: FastAPI (Asynchronous Server Gateway Interface).
* Database Layer: PostgreSQL managed via Supabase Client integrations.
* Tunneling Architecture: ngrok secure ingress proxy.
* Data Validation: Pydantic Core v2 typing models.

---

## 🚀 Quickstart Local Deployment

### 1. Environment Cloning & Initialization
Navigate into your local workspace directory and ensure your engineering dependencies are cleanly isolated inside your Conda environment:

cd D:\work\agri-pakistan\KapasKiSehat_Backend
conda activate ml

### 2. Dependency Ingestion
Install the required system packages and upstream client repositories:

pip install fastapi uvicorn pydantic supabase

### 3. Launching the Local Gateway
Execute the ASGI server module with hot-reloading explicitly enabled for immediate iterative debugging passes:

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

The local development gateway will expose its API documentation layer at: http://localhost:8000/docs

### 4. Activating the Ingress Proxy Tunnel
In a parallel terminal workspace session, spin up your ngrok tunnel instance targeting your active FastAPI application server port:

ngrok http 8000

Copy the generated secure .ngrok-free.dev forwarding URL domain and paste it directly into your Supabase Database Webhook portal layout interface, appending the target API routing extension: /api/v1/supabase-webhook

---

## 📁 Active API Reference Specifications

### 📡 System Integrity & Webhooks

#### GET /
* Purpose: Evaluates baseline core engine operational availability status.
* Response Payload: {"status": "online", "message": "..."}

#### POST /api/v1/supabase-webhook
* Purpose: Collects reactive event streams from Supabase on new database row inserts.
* Payload Blueprint (Pydantic Encapsulated):
{
  "type": "INSERT",
  "table": "diagnostic_logs",
  "schema_name": "public",
  "record": {
    "id": "55346551-3379-4960-8a8e-2119951d0d09",
    "device_id": "registered_node_hash",
    "confidence_score": 0.62,
    "district": "Multan",
    "whitefly_count": 14
  }
}

### 📱 Core Application Framework Endpoints

#### GET /api/v1/risk-metrics
* Parameters: district (Default: "Multan")
* Purpose: Supplies localized, regional risk metrics and climate telemetry directly to localized dashboards with full Urdu translations.

#### POST /api/v1/scan
* Payload: Multipart Form Data (file: UploadFile)
* Purpose: Processes incoming target crop imagery samples, utilizing mock inference buffers to provide standardized confidence mapping arrays.

#### POST /api/v1/chat
* Payload: Form Fields (message: str, language: str)
* Purpose: Level-1 triage conversational model supporting direct Urdu text parsing for pest mitigation strategies.

---

## 🗄️ Relational Database Schema Model

The local background workflow relies on strict foreign key integrity matching between the following table configurations inside your Supabase cluster:

* farmers_profiles: Tracks explicit physical application nodes mapped directly to device registration properties (device_id).
* diagnostic_logs: Captures real-time diagnostic event logs from field operations. Rows enforce strict database level constraints requiring a valid device_id linkage, alongside required default markers for district, whitefly_count, and confidence_score.

---

## 🤝 Project Roadmap & Next Phases

- [x] Configure end-to-end webhook architecture from cloud to local engine.
- [x] Implement asynchronous background task workers using FastAPI.
- [x] Integrate full database write-back mechanisms via the Python Supabase Client.
- [ ] Migrate raw credentials from application code strings into secure .env secret managers.
- [ ] Implement the live high-fidelity Computer Vision model inside the run_gatekeeper_verification block to replace the active stub model framework.