# CONTRACTS.md — KapasKiSehat_Backend (working source of truth)

> **Scope:** The backend's working source of truth for the data contracts it
> participates in: Supabase DB + Storage, webhooks, the `/api/v1/*` endpoints.
> Tracks both the **canonical contract** and where `main.py` conforms or deviates.
>
> **Provenance:** Canonical shapes/enums/column names synced **from**
> `MASTER-CONTRACTS.md` v2 (last merged **2026-06-02**). When MASTER is refreshed,
> re-sync this file from it. Do not treat MASTER as live truth on its own —
> **this file** governs backend changes.
> **Last verified against `main.py`:** 2026-06-03 (every conformance claim
> checked line-by-line against actual source).
>
> ML model: `Flee-v1.0.4-stb` (local, via ngrok). Stub: `mobilenet_v2` from
> `cottonace_stub.pth`.

---

## 0. Architecture (who owns what)

```
Android app → POST /api/v1/scan (image+GPS) → ScanResponse
            → upload JPEG to Storage "leaf-images/{device_id}/{epoch_ms}.jpg"
            → INSERT diagnostic_logs (ALL required fields, REAL values)
                        │ Supabase webhook on INSERT
                        ▼
Backend → POST /api/v1/supabase-webhook
        → if confidence_score < 0.75: download image, re-run ML,
          UPDATE diagnostic_logs (confidence_score, risk_level only)
                        │ Supabase Realtime
                        ▼
Next.js dashboard (read-only)
```

**Ownership rule:** the app owns all INSERTs. The backend only ever UPDATEs
`confidence_score` + `risk_level` on the gatekeeper path. The dashboard is
strictly read-only.

---

## 1. Supabase Table Schemas

Schema managed manually via Supabase SQL Editor. No component owns migrations.

### 1.1 `diagnostic_logs`

| Column               | Type               | Nullable | Owner    | Notes |
|----------------------|--------------------|----------|----------|-------|
| `id`                 | `uuid`             | NO       | Supabase | PK, auto-generated |
| `device_id`          | `varchar`          | YES      | App      | **FK → `farmers_profiles.device_id`** (`diagnostic_logs_device_id_fkey`). If non-null must already exist |
| `timestamp`          | `timestamptz`      | YES      | App      | Client event time (ISO-8601 UTC) |
| `district`           | `varchar`          | **NO**   | App      | Required |
| `whitefly_count`     | `integer`          | **NO**   | App      | Required. Real value from ML response |
| `risk_level`         | `varchar`          | **NO**   | App      | Required. Canonical enum — §4 |
| `confidence_score`   | `numeric`          | **NO**   | App      | Required. Real `ScanResponse.confidence`, 0.0–1.0 |
| `inference_time_ms`  | `integer`          | **NO**   | App      | Required. Actual measured duration |
| `image_storage_path` | `text`             | YES      | App      | Bare object key in `leaf-images`: `{device_id}/{epoch_ms}.jpg` — no bucket prefix, no leading slash |
| `created_at`         | `timestamptz`      | YES      | Supabase | Auto |
| `latitude`           | `double precision` | YES      | App      | GPS. `null` when unavailable — **NOT `0.0`** |
| `longitude`          | `double precision` | YES      | App      | GPS. `null` when unavailable — **NOT `0.0`** |
| `agricultural_belt`  | `varchar`          | YES      | App      | e.g. `"Southern Punjab"` |

> ❌ NO `status` column. ❌ NO `image_url` column. Use `image_storage_path`.

### 1.2 `farmers_profiles`

| Column               | Type          | Nullable | Notes |
|----------------------|---------------|----------|-------|
| `id`                 | `uuid`        | NO       | PK |
| `device_id`          | `varchar`     | **NO**   | Unique device identity (SHA-256 hash) |
| `registered_at`      | `timestamptz` | YES      | |
| `last_active_at`     | `timestamptz` | YES      | |
| `app_version`        | `varchar`     | **NO**   | gradle `versionName` (currently `"1.0"`) |
| `preferred_language` | `varchar`     | **NO**   | Code from §5 — `"ur"` not `"URDU"` |

### 1.3 `model_deployments`

| Column                  | Type          | Nullable | Notes |
|-------------------------|---------------|----------|-------|
| `id`                    | `uuid`        | NO       | PK |
| `model_version`         | `varchar`     | **NO**   | e.g. `"Flee-v1.0.4-stb"` |
| `deployed_at`           | `timestamptz` | YES      | |
| `dataset_size_leaves`   | `integer`     | **NO**   | |
| `f1_score`              | `numeric`     | **NO**   | **Flat column** — NOT `scores.f1` |
| `precision_score`       | `numeric`     | **NO**   | **Flat column** — NOT `precision` |
| `recall_score`          | `numeric`     | **NO**   | **Flat column** — NOT `recall` |
| `is_active_fleet_model` | `boolean`     | YES      | Only one row `true` at a time |

### 1.4 `harvested_images_pool`

| Column                   | Type          | Nullable | Notes |
|--------------------------|---------------|----------|-------|
| `id`                     | `uuid`        | NO       | |
| `device_id`              | `varchar`     | **NO**   | |
| `district`               | `varchar`     | **NO**   | |
| `confidence_score`       | `numeric`     | **NO**   | |
| `storage_bucket_path`    | `text`        | **NO**   | |
| `harvested_at`           | `timestamptz` | YES      | |
| `ai_studio_verification` | `varchar`     | YES      | Human/AI label |

### 1.5 `system_health_telemetry`

| Column        | Type          | Nullable | Notes |
|---------------|---------------|----------|-------|
| `id`          | `bigint`      | NO       | Auto-increment |
| `device_id`   | `varchar`     | YES      | |
| `log_level`   | `varchar`     | **NO**   | `INFO` \| `WARN` \| `ERROR` |
| `component`   | `varchar`     | **NO**   | Subsystem name |
| `message`     | `text`        | **NO**   | |
| `stack_trace` | `text`        | YES      | |
| `created_at`  | `timestamptz` | YES      | |

---

## 2. Supabase Storage

| Bucket        | App    | Backend | Purpose |
|---------------|--------|---------|---------|
| `leaf-images` | writes | reads   | Captured leaf images for ML re-verification |

- **Object path format (frozen — §11):** `{device_id}/{epoch_ms}.jpg`
  Stored as a **bare key** — no bucket prefix, no leading slash.
  Rationale: `download_leaf_image()` tolerates several forms, but the canonical
  one-format rule prevents ambiguity across repos.
- **App:** upload after `/api/v1/scan`; store the returned path in
  `image_storage_path` on INSERT.
- **Backend:** gatekeeper downloads via `image_storage_path`. If null/empty →
  **skip re-verification** (don't overwrite edge values).
- Bucket configurable via `SUPABASE_STORAGE_BUCKET` (default `leaf-images`).
- `download_leaf_image()` uses `_storage_client` (service-role key if
  `SUPABASE_SERVICE_KEY` is set, else anon key). Anon key works for public
  buckets only; set the service key for private buckets.

---

## 3. API Contracts

### 3.1 `POST /api/v1/scan` — Mobile → Backend
`multipart/form-data` — **frozen per §11; do not modify during image-upload chain work.**

| Field       | Type   | Required | Canonical | Backend now |
|-------------|--------|----------|-----------|-------------|
| `file`      | binary | YES      | JPEG      | ✅ |
| `latitude`  | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` (held — §11) |
| `longitude` | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` (held — §11) |

**Success (`200`):**
```jsonc
{
  "status": "success",
  "prediction": "Yellowish_Leaf",   // one of CLASSES (§6)
  "confidence": 0.87,               // 0.0–1.0, rounded 2dp
  "confidence_score": 0.87,         // duplicate of confidence
  "pest_type": "Whitefly",          // "Whitefly" | "None"
  "whitefly_count": 12,             // ⚠️ hardcoded stub (held — §11)
  "action_protocol": "…",           // English (== recommendation_en)
  "recommendation_en": "…",         // ⚠️ wording differs from §7 (held — §11)
  "recommendation_ur": "…",
  "latitude": 30.157,               // echoed
  "longitude": 71.524
}
```
**Error:** `{ "status": "error", "message": "<text>" }`

> `/scan` does **not** write `diagnostic_logs`. The app INSERTs after the response.

### 3.2 `POST /api/v1/supabase-webhook` — Supabase → Backend
**Frozen per §11; do not modify during image-upload chain work.**

```jsonc
{
  "type": "INSERT",
  "table": "diagnostic_logs",
  "schema": "public",          // ✅ aliased: Pydantic maps "schema" → schema_name
  "record": { /* full row */ },
  "old_record": null
}
```

| Condition | Response |
|-----------|----------|
| Queued | `{"status":"accepted","message":"Payload queued for system execution processing"}` |
| Duplicate | `{"status":"ignored","message":"Duplicate event transaction already processing"}` |

Trigger: `record.confidence_score < 0.75` (missing → `1.0` → no trigger).
Updates **only** `confidence_score` + `risk_level`. De-dup in-memory, lost on restart.

### 3.3 `GET /api/v1/risk-metrics` — Dashboard/App → Backend ✅

```jsonc
{
  "district": "MULTAN",
  "temperature": 37.0,         // ✅ numeric (was "37°C")
  "humidity": 42.0,            // ✅ numeric (was "42%")
  "wind_speed": 14.0,          // ✅ numeric (was "14 km/h")
  "risk_level": "CRITICAL",    // ✅ canonical enum §4 (was "CRITICAL WHITEFLY RISK")
  "alert_text_en": "…",
  "alert_text_ur": "…"
}
```
All values are stubs until this endpoint is wired to real weather/telemetry.
Neither the app nor the dashboard consumes this endpoint yet.

### 3.4 `POST /api/v1/chat` — App → Backend ✅

**Request (JSON body):** ✅ (was `Form(...)`)
```jsonc
{ "message": "سفید مکھی کا علاج کیسے کریں", "language": "ur" }
```
**Response:** `{ "reply": "…urdu text…" }`

Keyword matching (Urdu):
| Trigger | Reply topic |
|---------|-------------|
| `مکھی` / `سفید` | Spray timing guidance |
| `پانی` / `آبپاشی` | Irrigation during heatwave |
| _(default)_ | Generic inspection message |

App expert screen is a static stub and does not call this yet.

---

## 4. Risk Level Enum (Canonical)

> All components — **uppercase, no spaces.**

| Value      | Meaning                        | Whitefly count band |
|------------|--------------------------------|---------------------|
| `LOW`      | Healthy / below threshold      | 0–4 |
| `MEDIUM`   | Monitor; localized presence    | 5–8 |
| `HIGH`     | Action recommended             | 9–15 |
| `CRITICAL` | Outbreak; immediate mitigation | 16+ |

**Dashboard marker colors** (`utils/types.ts`): LOW `#6BE675` · MEDIUM `#F4B740` ·
HIGH `#F58B40` · CRITICAL `#F45B5B` · unknown → `#9CA3AF`.

- ✅ Gatekeeper worker: `derive_risk_level(whitefly_count)` — `Fresh_Leaf` → `LOW`,
  else by count band.
- ✅ `/risk-metrics`: now emits `"CRITICAL"` (was free text).
- DB: unconstrained `varchar` — recommend a CHECK constraint.
- **Nuance:** image model is a classifier; it does not count whiteflies. Worker
  derives risk from the app-supplied `whitefly_count`.

---

## 5. Language Codes (Canonical)

| Language | Code  | `AppLanguage` enum | Display |
|----------|-------|--------------------|---------|
| Urdu     | `ur`  | `URDU` (default)   | اردو    |
| Punjabi  | `pa`  | `PUNJABI`          | پنجابی  |
| Saraiki  | `skr` | `SARAIKI`          | سرائیکی |
| English  | `en`  | `ENGLISH`          | EN      |

Use **codes** on the wire (`ur/pa/skr/en`). ❌ Never send `"URDU"`.
Backend `ChatRequest.language` defaults to `"ur"`.

---

## 6. ML Model Constants

### Class labels (`CLASSES`)
```
Fresh_Leaf                 → healthy,         pest_type = "None"
Leaf_Reddening             → disease present, pest_type = "Whitefly"
Leaf_Spot_Bacterial_Blight → disease present, pest_type = "Whitefly"
Yellowish_Leaf             → disease present, pest_type = "Whitefly"
```

- **Model version:** `Flee-v1.0.4-stb` — active via `is_active_fleet_model = true`
- **Confidence threshold:** `0.75` — gatekeeper re-verifies below this
- **Confidence scale:** `0.0–1.0` always. Dashboard renders `×100%`.

---

## 7. Recommendation / Action Protocol (§7)

| Condition | `recommendation_ur` | `recommendation_en` (canonical) |
|-----------|---------------------|---------------------------------|
| Whitefly detected | سفید مکھی کے تدارک کے لیے متعلقہ اسپرے صبح یا شام کے وقت کریں۔ | Apply targeted mitigation spray in morning or evening. |
| Healthy | کپاس کی فصل صحت مند ہے۔ کسی اسپرے کی ضرورت نہیں ہے۔ | Crop is healthy. No spray required. |

> ⚠️ Backend `/scan` currently returns `"Apply targeted mitigation if pest status
> is confirmed."` — differs from canonical. Held (touches `/scan`, frozen per §11).

---

## 8. Backend Conformance

### ✅ Conforms / fixed
| Item | Notes |
|------|-------|
| No `status` / `image_url` column | Confirmed PGRST204 live 2026-06-01; fixed |
| Worker reads `image_storage_path` | Was `image_url` |
| Worker scores real image | Was `torch.randn()` noise |
| Skip when `image_storage_path` empty | Leaves edge values untouched |
| `SUPABASE_STORAGE_BUCKET` from env | Default `leaf-images` |
| `SUPABASE_SERVICE_KEY` optional | `_storage_client` uses it when set; anon fallback |
| 4-level `risk_level` in worker | `derive_risk_level()` — verified live |
| Webhook `schema` alias | `Field(alias="schema")` + `populate_by_name=True` |
| `MODEL_PATH` from env | No hardcoded absolute path |
| CORS configured | `CORSMiddleware`; origins via `CORS_ALLOW_ORIGINS` |
| `sys.stdout.reconfigure("utf-8")` | Prevents emoji crash on cp1252 consoles |
| `/risk-metrics` numeric + canonical | `37.0`, `"CRITICAL"` etc. |
| `/chat` JSON body | `ChatRequest` Pydantic model |

### 🔒 Frozen (touches `/scan` or webhook — held per §11 guardrails)
| Item | Hold reason |
|------|-------------|
| GPS `0.0` → `null` in `/scan` | Modifies `/scan` response |
| `recommendation_en` wording | Modifies `/scan` response |
| `whitefly_count` hardcoded `12` | Model doesn't count; needs separate work |

### 🟡 Known / hygiene
- In-memory webhook de-dup lost on restart
- No webhook signature verification
- `.env` has live credentials — confirm gitignored; rotate if needed

---

## 9. Cross-Repo Conformance (backend-relevant, from MASTER v2 §9)

> ⚠️ The **App** column below reflects MASTER v2 state (2026-06-02) and may be
> stale — App fixes made after that date won't appear here until the next MASTER
> refresh. Do not update App cells in this file; let the next MASTER sync correct them.

| Contract point | App | Backend | Dashboard |
|----------------|-----|---------|-----------|
| No `status`/`image_url` column | ✅ | ✅ | ✅ |
| Webhook `schema` key | n/a | ✅ | n/a |
| Risk enum 4-level | 🔴 CRITICAL/MEDIUM only | ✅ | ✅ |
| `/risk-metrics` numeric + canonical | not consumed | ✅ | not consumed |
| `/chat` JSON body | not consumed | ✅ | not consumed |
| GPS `null` not `0.0` | 🟠 | 🟠 held | ✅ |
| Image upload to Storage | 🔴 not yet | ✅ ready | n/a |
| Real `confidence_score` | 🔴 hardcoded 0.95 | ✅ | reads real |
| Real `whitefly_count` | 🔴 fabricated | 🟡 hardcodes 12 | reads value |
| `preferred_language` code | ✅ | only `ur` referenced | n/a |

Legend: ✅ conforms · 🟠 open/non-breaking · 🔴 blocks pipeline · 🟡 known stub

---

## 10. Environment Variables (Backend `.env`)

| Variable                  | Example                         | Notes |
|---------------------------|---------------------------------|-------|
| `SUPABASE_URL`            | `https://xxx.supabase.co`       | |
| `SUPABASE_KEY`            | `sb_publishable_…`              | Anon key. Used for DB + public Storage |
| `SUPABASE_SERVICE_KEY`    | `sb_secret_…`                   | Optional. Used for private Storage reads by `_storage_client`. Set once `leaf-images` bucket is created |
| `SUPABASE_STORAGE_BUCKET` | `leaf-images`                   | |
| `MODEL_PATH`              | `D:\...\cottonace_stub.pth`     | Machine-specific. Set in local `.env` |
| `NGROK_URL`               | `https://xxx.ngrok-free.dev`    | **Not read by backend code.** Manual step only: paste the ngrok URL into the Supabase webhook portal after each restart |
| `CORS_ALLOW_ORIGINS`      | `*` (dev) / `https://dashboard.example.com` (prod) | |

---

## 11. Current Cross-Repo Work Item (MASTER §11)

**The image-upload + real-data chain** — the keystone that activates the gatekeeper.

**Backend is frozen and ready for this chain.** Do NOT modify `/scan`, the
webhook handler, or `download_leaf_image()` during this work item. If a real bug
surfaces, flag it for a MASTER revision rather than silently changing the read path.

**Frozen contracts for this chain:**
- Bucket: `leaf-images`
- Object path: `{device_id}/{epoch_ms}.jpg` (bare key, no prefix, no leading slash)
- Backend UPDATEs only `confidence_score` + `risk_level`

**Steps (sequenced):**
- **Step 0 (Supabase, you):** create `leaf-images` bucket; decide public vs private;
  set storage RLS policy for app uploads. If private, add `SUPABASE_SERVICE_KEY`
  to backend `.env`. Verify by uploading one file and confirming backend can download.
- **Steps 1–3 (App):** extend DTOs → add Storage upload → write real values on INSERT.
- **Step 4 (all):** end-to-end test with a `confidence < 0.75` scan.

**Definition of done:** (1) image in `leaf-images`, (2) row with real values + non-null
`image_storage_path`, (3) backend gatekeeper UPDATE fires on sub-0.75 confidence,
(4) dashboard reflects it live. Closes MASTER §10 issues #1–#5.
