# Kapas Ki Sehat (CottonAce) - Backend Core Engine 🌾🛡️

An event-driven, asynchronous MLOps backend architecture designed for the early detection and triage of Whitefly infestations in cotton crops across Pakistan's agricultural belts. This repository serves as the "Walking Skeleton" infrastructure, bridging mobile telemetry data, cloud storage schemas, and local automated machine learning validation handlers.

---

## 🏗️ Architectural Overview

The engine operates on a reactive, event-driven loop to process field diagnostics without blocking client-side mobile execution:

1. **Telemetry Ingestion:** Mobile devices insert diagnostic telemetry (leaf imagery paths, coordinates, and edge device confidence scores) into a remote Supabase PostgreSQL instance.
2. **Webhooks Edge Trigger:** A strict database constraint trigger monitors inserts on the logging schema and immediately fires an HTTP POST payload over an active `ngrok` reverse-proxy tunnel to this local engine.
3. **Asynchronous Triage Worker:** If the edge model's confidence falls below an established operational threshold ($< 0.75$), FastAPI intercepts the payload and provisions an isolated background task.
4. **Closed-Loop Synchronization:** The background worker runs an analytical stub evaluation pass (mimicking higher-fidelity validation models) and automatically updates the database row state, updating the Next.js administration dashboard in real time.

---

## 🛠️ System Pre-requisites & Stack

* **Runtime Environment:** Python 3.10+ managed via Anaconda/Conda.
* **Core Framework:** FastAPI (Asynchronous Server Gateway Interface).
* **Database Layer:** PostgreSQL managed via Supabase Client integrations.
* **Tunneling Architecture:** ngrok secure ingress proxy.
* **Data Validation:** Pydantic Core v2 typing models.

---

## 🚀 Quickstart Local Deployment

### 1. Environment Cloning & Initialization
Navigate into your local workspace directory and ensure your engineering dependencies are cleanly isolated inside your Conda environment:

```bash
# Clone or step into your working directory
cd D:\work\agri-pakistan\KapasKiSehat_Backend

# Activate your designated machine learning workspace
conda activate ml