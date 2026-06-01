# MASTER-CONTRACTS.md — Kapas Ki Sehat (CottonAce)

> **This is the single source of truth** for all data contracts shared across:
> - `Kapas-Ki-Sehat` (Android / Kotlin)
> - `KapasKiSehat_Backend` (FastAPI / Python)
> - `KapasKiSehat_Dashboard` (Next.js / TypeScript)
>
> **Place a copy of this file at the root of all three repos.**
> When any contract changes, update this file first, then update all affected components.
>
> Last updated: 2026-06-01

---

## 0. System Architecture

```
┌─ Android App (Kotlin) ──────────────────────────────────────────┐
│  1. Capture image                                                │
│  2. POST /api/v1/scan → FastAPI (image + lat/lon)               │
│  3. Receive ScanResponse                                         │
│  4. Upload image to Supabase Storage bucket: "leaf-images"      │
│     → store returned path as image_storage_path                 │
│  5. INSERT diagnostic_logs row (with ALL required fields)        │
│  6. Upsert farmers_profiles row                                  │
└──────────────────────────────────────────────────────────────────┘
         │ Supabase webhook on INSERT
         ▼
┌─ FastAPI Backend ────────────────────────────────────────────────┐
│  POST /api/v1/supabase-webhook                                   │
│  → if confidence_score < 0.75:                                   │
│      download image from Supabase Storage                        │
│      run ML re-verification (Flee-v1.0.4-stb)                   │
│      UPDATE diagnostic_logs (confidence_score, risk_level only)  │
└──────────────────────────────────────────────────────────────────┘
         │ Supabase Realtime
         ▼
┌─ Next.js Dashboard ──────────────────────────────────────────────┐
│  Read-only. Subscribes to diagnostic_logs via Realtime.          │
│  Displays counts, map, MLOps panel.                              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 1. Supabase Tables (Source of Truth)

> Schema is managed manually via Supabase SQL Editor.
> No component owns migrations. All components must conform to these definitions.

### 1.1 `diagnostic_logs`

| Column               | Type               | Nullable | Owner    | Notes |
|----------------------|--------------------|----------|----------|-------|
| `id`                 | `uuid`             | NO       | Supabase | Primary key, auto-generated |
| `device_id`          | `varchar`          | YES      | App      | FK → `farmers_profiles.device_id` |
| `timestamp`          | `timestamptz`      | YES      | App      | Client-side event time (ISO-8601 UTC) |
| `district`           | `varchar`          | **NO**   | App      | Required. Use `agricultural_belt` value |
| `whitefly_count`     | `integer`          | **NO**   | App      | Required. From ML response |
| `risk_level`         | `varchar`          | **NO**   | App      | Required. See §4 for canonical enum |
| `confidence_score`   | `numeric`          | **NO**   | App      | Required. **Real value from ScanResponse**, 0.0–1.0 |
| `inference_time_ms`  | `integer`          | **NO**   | App      | Required. Measure actual inference duration |
| `image_storage_path` | `text`             | YES      | App      | Path in Supabase Storage bucket `leaf-images` |
| `created_at`         | `timestamptz`      | YES      | Supabase | Auto set by DB |
| `latitude`           | `double precision` | YES      | App      | GPS. Send `null` if unavailable — NOT `0.0` |
| `longitude`          | `double precision` | YES      | App      | GPS. Send `null` if unavailable — NOT `0.0` |
| `agricultural_belt`  | `varchar`          | YES      | App      | Region grouping e.g. `"Southern Punjab"` |

> ❌ There is NO `status` column. Do not reference it anywhere.
> ❌ There is NO `image_url` column. Use `image_storage_path`.

### 1.2 `farmers_profiles`

| Column               | Type          | Nullable | Owner | Notes |
|----------------------|---------------|----------|-------|-------|
| `id`                 | `uuid`        | NO       | Supabase | Primary key |
| `device_id`          | `varchar`     | **NO**   | App   | Unique device identity (SHA-256 hash) |
| `registered_at`      | `timestamptz` | YES      | App   | |
| `last_active_at`     | `timestamptz` | YES      | App   | |
| `app_version`        | `varchar`     | **NO**   | App   | Use gradle `versionName`, currently `"1.0"` |
| `preferred_language` | `varchar`     | **NO**   | App   | See §5 language codes. Use `"ur"` not `"URDU"` |

### 1.3 `model_deployments`

| Column                  | Type          | Nullable | Notes |
|-------------------------|---------------|----------|-------|
| `id`                    | `uuid`        | NO       | Primary key |
| `model_version`         | `varchar`     | **NO**   | e.g. `"Flee-v1.0.4-stb"` |
| `deployed_at`           | `timestamptz` | YES      | |
| `dataset_size_leaves`   | `integer`     | **NO**   | |
| `f1_score`              | `numeric`     | **NO**   | Flat column — NOT nested under `scores` |
| `precision_score`       | `numeric`     | **NO**   | Flat column — NOT `precision` |
| `recall_score`          | `numeric`     | **NO**   | Flat column — NOT `recall` |
| `is_active_fleet_model` | `boolean`     | YES      | Only one row should be `true` at a time |

> ✅ Dashboard must read `f1_score`, `precision_score`, `recall_score` (flat columns).
> ❌ Do NOT read `scores.f1`, `scores.precision`, `scores.recall` — that nested shape does not exist.

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

| Bucket        | Used by | Purpose |
|---------------|---------|---------|
| `leaf-images` | App → writes, Backend → reads | Captured leaf images for ML re-verification |

**App upload flow:**
1. After receiving `ScanResponse` from `/api/v1/scan`, upload the JPEG to `leaf-images/{device_id}/{epoch_ms}.jpg`
2. Store the returned storage path in `image_storage_path` when inserting `diagnostic_logs`

**Backend read flow:**
- Gatekeeper worker downloads via `image_storage_path` from the `leaf-images` bucket
- If `image_storage_path` is null/empty, skip re-verification entirely

---

## 3. API Contracts

### 3.1 `POST /api/v1/scan` — Mobile → Backend

**Request** (`multipart/form-data`):

| Field       | Type   | Required | Notes |
|-------------|--------|----------|-------|
| `file`      | binary | YES      | JPEG, `filename="scan_{epochMillis}.jpg"` |
| `latitude`  | float  | NO       | Send `null` if unavailable — NOT `0.0` |
| `longitude` | float  | NO       | Send `null` if unavailable — NOT `0.0` |

**Success Response** (`200 OK`):
```jsonc
{
  "status": "success",
  "prediction": "Yellowish_Leaf",    // one of CLASSES — see §6
  "confidence": 0.87,                // 0.0–1.0
  "confidence_score": 0.87,          // same as confidence (duplicate field)
  "pest_type": "Whitefly",           // "Whitefly" | "None"
  "whitefly_count": 12,              // ⚠️ currently hardcoded — treat as estimate
  "action_protocol": "…",            // English guidance
  "recommendation_en": "…",          // English (same as action_protocol)
  "recommendation_ur": "…",          // Urdu guidance
  "latitude": 30.157,                // echoed back
  "longitude": 71.524
}
```

**Error Response:**
```jsonc
{ "status": "error", "message": "<exception text>" }
```

> ⚠️ `/api/v1/scan` does NOT write to `diagnostic_logs`.
> The Android app is responsible for the INSERT after receiving this response.

### 3.2 `POST /api/v1/supabase-webhook` — Supabase → Backend

**Supabase sends** (canonical envelope):
```jsonc
{
  "type": "INSERT",
  "table": "diagnostic_logs",
  "schema": "public",          // key is "schema" NOT "schema_name"
  "record": {                  // full diagnostic_logs row
    "id": "uuid",
    "device_id": "…",
    "district": "Multan Belt",
    "whitefly_count": 14,
    "risk_level": "MEDIUM",
    "confidence_score": 0.62,
    "inference_time_ms": 145,
    "image_storage_path": "leaf-images/abc123/1234567890.jpg",
    "latitude": 30.157,
    "longitude": 71.524,
    "agricultural_belt": "Southern Punjab",
    "created_at": "2026-06-01T10:00:01+00:00"
  },
  "old_record": null
}
```

**Backend response:**
```jsonc
// Queued for processing:
{ "status": "accepted", "message": "Payload queued for system execution processing" }

// Duplicate event:
{ "status": "ignored", "message": "Duplicate event transaction already processing" }
```

**Gatekeeper trigger rule:**
- Fires only when `record.confidence_score < 0.75`
- Downloads image from `record.image_storage_path` (bucket: `leaf-images`)
- Runs ML re-verification
- Updates `diagnostic_logs` — only `confidence_score` and `risk_level` columns

### 3.3 `GET /api/v1/risk-metrics` — Dashboard / App → Backend

**Response:**
```jsonc
{
  "temperature": 37.0,
  "humidity": 42.0,
  "wind_speed": 14.0,
  "risk_level": "CRITICAL",       // canonical enum value — see §4
  "alert_text_en": "…",
  "alert_text_ur": "…"
}
```

### 3.4 `POST /api/v1/chat` — App → Backend

**Request:**
```jsonc
{ "message": "سفید مکھی کا علاج کیسے کریں", "language": "ur" }
```

**Response:**
```jsonc
{ "reply": "…urdu text…" }
```

---

## 4. Risk Level Enum (Canonical)

> **All three components must use exactly these values, uppercase, no spaces.**

| Value      | Meaning                              | Whitefly count band |
|------------|--------------------------------------|---------------------|
| `LOW`      | Healthy / below threshold            | 0–4                 |
| `MEDIUM`   | Monitor; localized presence          | 5–8                 |
| `HIGH`     | Action recommended                   | 9–15                |
| `CRITICAL` | Outbreak; immediate mitigation       | 16+                 |

**Rules:**
- Android app: derive from `ScanResponse.confidence` AND `whitefly_count`
- Backend: emit only these four values from the gatekeeper worker
- Dashboard: handle all four values — `=== 'CRITICAL'` filter is insufficient
- DB: `risk_level varchar NOT NULL` — recommend adding a CHECK constraint

---

## 5. Language Codes (Canonical)

| Language | Code  | Display label |
|----------|-------|---------------|
| Urdu     | `ur`  | اردو          |
| Punjabi  | `pa`  | پنجابی        |
| Saraiki  | `skr` | سرائیکی       |
| English  | `en`  | EN            |

> ✅ Use these codes everywhere: `farmers_profiles.preferred_language`, `/chat` `language` field, app `AppLanguage` enum.
> ❌ Do NOT use `"URDU"`, `"ENGLISH"` etc. (full uppercase names).

---

## 6. ML Model Constants

### Class labels (`CLASSES`) — Backend `main.py`
These are the raw model output strings. All components interpreting `prediction` must use these exact values:

```
Fresh_Leaf              → healthy, pest_type = "None"
Leaf_Reddening          → disease present, pest_type = "Whitefly"
Leaf_Spot_Bacterial_Blight → disease present, pest_type = "Whitefly"
Yellowish_Leaf          → disease present, pest_type = "Whitefly"
```

### Model version
`Flee-v1.0.4-stb` — active model flagged via `model_deployments.is_active_fleet_model = true`

### Confidence threshold
`0.75` — gatekeeper re-verification triggers below this value

### Confidence scale
Always `0.0–1.0`. Never `0–100`. Dashboard renders `Math.round(score * 100) + "%"`.

---

## 7. Recommendation / Action Protocol

Returned by `/api/v1/scan` in `recommendation_ur` and `recommendation_en`.

| Condition | `recommendation_ur` | `recommendation_en` |
|-----------|---------------------|---------------------|
| Whitefly detected | سفید مکھی کے تدارک کے لیے متعلقہ اسپرے صبح یا شام کے وقت کریں۔ | Apply targeted mitigation spray in morning or evening. |
| Healthy | کپاس کی فصل صحت مند ہے۔ کسی اسپرے کی ضرورت نہیں ہے۔ | Crop is healthy. No spray required. |

---

## 8. Environment Variables

### Backend (`.env`)
| Variable                  | Example value                            | Notes |
|---------------------------|------------------------------------------|-------|
| `SUPABASE_URL`            | `https://xxx.supabase.co`                | |
| `SUPABASE_KEY`            | `sb_publishable_…`                       | anon/publishable key |
| `SUPABASE_STORAGE_BUCKET` | `leaf-images`                            | |
| `MODEL_PATH`              | `./models/cottonace_stub.pth`            | Do not hardcode absolute path |
| `NGROK_URL`               | `https://xxx.ngrok-free.dev`             | Update on each ngrok restart |

### Dashboard (`.env.local`)
| Variable                      | Notes |
|-------------------------------|-------|
| `NEXT_PUBLIC_SUPABASE_URL`    | Must match backend |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Same anon key |

### Android app
| Constant               | Current location          | Fix |
|------------------------|---------------------------|-----|
| Backend base URL       | `NetworkUtil.kt` hardcoded | Move to `BuildConfig` / `local.properties` |
| Supabase URL + key     | `CottonAceApplication.kt` hardcoded | Move to `local.properties` + Secrets plugin |

---

## 9. Known Issues / Remaining TODOs

| # | Severity | Component | Issue |
|---|----------|-----------|-------|
| 1 | 🔴 | App | Image never uploaded to Supabase Storage — `image_storage_path` always null, gatekeeper never runs |
| 2 | 🔴 | App | `confidence_score` hardcoded `0.95f` — use real `ScanResponse.confidence` |
| 3 | 🔴 | App | `whitefly_count` fabricated — use real `ScanResponse.whitefly_count` |
| 4 | 🔴 | App | `inference_time_ms` hardcoded `150` — measure actual time |
| 5 | 🟠 | App | `preferred_language` sends `"URDU"` — must send `"ur"` |
| 6 | 🟠 | App | `app_version` sends `"2.4"` — must match gradle `versionName` |
| 7 | 🟠 | App | Location defaults to `0.0/0.0` — send `null` when unavailable |
| 8 | 🟠 | App | `imagePath` uses mock path in `DataSyncWorker` — use real captured file path |
| 9 | 🟠 | Dashboard | `model_deployments` reads `scores.f1` — must read flat `f1_score` |
| 10 | 🟠 | Dashboard | `risk_level` only handles `CRITICAL` — handle all 4 enum values |
| 11 | 🟠 | Dashboard | Map markers not color-coded by `risk_level` |
| 12 | 🟠 | Dashboard | "Mean Engine Confidence" is static `89.4%` — compute from real data |
| 13 | 🟠 | Dashboard | Telemetry stream is fake hardcoded strings |
| 14 | 🟠 | Backend | Webhook field `schema_name` should be aliased to `schema` |
| 15 | 🟠 | Backend | No CORS middleware configured — dashboard browser requests may be blocked |
| 16 | 🟡 | Backend | `whitefly_count` in `/scan` response hardcoded to `12` |
| 17 | 🟡 | Backend | In-memory deduplication lost on restart |
| 18 | 🟡 | Backend | No webhook signature verification |
| 19 | 🟡 | All | Supabase credentials committed to source — rotate and gitignore |
| 20 | 🟡 | All | No shared `RiskLevel` enum/constant — each component uses raw strings |

---

## 10. Quick Sync Checklist

Before pushing changes that touch shared contracts, verify:

- [ ] `diagnostic_logs` column names match §1.1 exactly
- [ ] `risk_level` value is one of `LOW / MEDIUM / HIGH / CRITICAL`
- [ ] `confidence_score` is on `0.0–1.0` scale
- [ ] `preferred_language` uses codes from §5
- [ ] `model_deployments` score columns are `f1_score / precision_score / recall_score`
- [ ] No component sends `0.0` for missing GPS — use `null`
- [ ] Backend URL in app updated if ngrok restarted
