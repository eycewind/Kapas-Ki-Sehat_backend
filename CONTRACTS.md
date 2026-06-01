# CONTRACTS.md — KapasKiSehat_Backend (working source of truth)

> **Scope:** This is the **backend's** working source of truth for the data
> contracts it participates in (Supabase DB + Storage, webhooks, the `/api/v1/*`
> endpoints). It tracks both the **canonical contract** and **where the current
> `main.py` code actually conforms or deviates**.
>
> **Provenance:** Canonical shapes/enums/column names here are synced **from**
> `MASTER-CONTRACTS.md` (the cross-repo aggregate, last synced **2026-06-01**).
> `MASTER-CONTRACTS.md` is regenerated periodically from all three repos and may
> lag the live backend — when it is refreshed, re-sync this file from it. Do not
> treat MASTER as live truth on its own; **this file** governs backend changes.
>
> ML model: `Flee-v1.0.4-stb` (local, exposed via ngrok). Backend currently runs
> a stub: `mobilenet_v2` from `cottonace_stub.pth`.

---

## 0. Architecture (who owns what)

```
Android app → POST /api/v1/scan (image+GPS) → ScanResponse
            → upload JPEG to Storage bucket "leaf-images"
            → INSERT diagnostic_logs (ALL required fields, real values)
                        │ Supabase webhook on INSERT
                        ▼
Backend → POST /api/v1/supabase-webhook
        → if confidence_score < 0.75: download image, re-run ML,
          UPDATE diagnostic_logs (confidence_score, risk_level only)
                        │ Supabase Realtime
                        ▼
Next.js dashboard (read-only): counts, map, MLOps panel
```

The app owns all `diagnostic_logs` / `farmers_profiles` INSERTs. The backend
only ever **UPDATEs** `confidence_score` + `risk_level` on the gatekeeper path.

---

## 1. Supabase Table Schemas

Schema is managed **manually via the SQL Editor**. No component owns migrations;
all must conform.

### 1.1 `diagnostic_logs`
A new row INSERT here fires the webhook.

| Column                | Type               | Nullable | Owner | Notes |
| --------------------- | ------------------ | -------- | ----- | ----- |
| `id`                  | `uuid`             | NO       | Supabase | Primary key, auto-generated |
| `device_id`           | `varchar`          | YES      | App | **FK → `farmers_profiles.device_id`** (`diagnostic_logs_device_id_fkey`). If non-null must already exist in `farmers_profiles` |
| `timestamp`           | `timestamptz`      | YES      | App | Client event time (ISO-8601 UTC) |
| `district`            | `varchar`          | **NO**   | App | Required. Use the `agricultural_belt` value |
| `whitefly_count`      | `integer`          | **NO**   | App | Required. From ML response |
| `risk_level`          | `varchar`          | **NO**   | App | Required. Canonical enum — see [§4](#4-risk-level-enum-canonical) |
| `confidence_score`    | `numeric`          | **NO**   | App | Required. **Real** value, 0.0–1.0 |
| `inference_time_ms`   | `integer`          | **NO**   | App | Required. Actual measured duration |
| `image_storage_path`  | `text`             | YES      | App | Object path in Storage bucket `leaf-images` |
| `created_at`          | `timestamptz`      | YES      | Supabase | Auto |
| `latitude`            | `double precision` | YES      | App | GPS. Send `null` when unavailable — **NOT `0.0`** |
| `longitude`           | `double precision` | YES      | App | GPS. Send `null` when unavailable — **NOT `0.0`** |
| `agricultural_belt`   | `varchar`          | YES      | App | Region group, e.g. `"Southern Punjab"` |

> ❌ There is **no `status` column** and **no `image_url` column**. Never
> reference either. (Both were referenced by old code — now fixed, see [§7](#7-backend-conformance-vs-canonical-contract).)

### 1.2 `farmers_profiles`
| Column               | Type          | Nullable | Notes |
| -------------------- | ------------- | -------- | ----- |
| `id`                 | `uuid`        | NO       | Primary key |
| `device_id`          | `varchar`     | **NO**   | Unique device identity (SHA-256 hash) |
| `registered_at`      | `timestamptz` | YES      | |
| `last_active_at`     | `timestamptz` | YES      | |
| `app_version`        | `varchar`     | **NO**   | gradle `versionName` (e.g. `"1.0"`) |
| `preferred_language` | `varchar`     | **NO**   | Code from [§5](#5-language-codes-canonical) — `"ur"` not `"URDU"` |

### 1.3 `harvested_images_pool`
Pool of images retained for retraining / human verification.

| Column                   | Type          | Nullable | Notes |
| ------------------------ | ------------- | -------- | ----- |
| `id`                     | `uuid`        | NO       | Primary key |
| `device_id`              | `varchar`     | **NO**   | |
| `district`               | `varchar`     | **NO**   | |
| `confidence_score`       | `numeric`     | **NO**   | |
| `storage_bucket_path`    | `text`        | **NO**   | |
| `harvested_at`           | `timestamptz` | YES      | |
| `ai_studio_verification` | `varchar`     | YES      | Human/AI label |

### 1.4 `model_deployments`
| Column                  | Type          | Nullable | Notes |
| ----------------------- | ------------- | -------- | ----- |
| `id`                    | `uuid`        | NO       | Primary key |
| `model_version`         | `varchar`     | **NO**   | e.g. `"Flee-v1.0.4-stb"` |
| `deployed_at`           | `timestamptz` | YES      | |
| `dataset_size_leaves`   | `integer`     | **NO**   | |
| `f1_score`              | `numeric`     | **NO**   | **Flat column** — NOT nested `scores.f1` |
| `precision_score`       | `numeric`     | **NO**   | **Flat column** — NOT `precision` |
| `recall_score`          | `numeric`     | **NO**   | **Flat column** — NOT `recall` |
| `is_active_fleet_model` | `boolean`     | YES      | Only one row `true` at a time |

### 1.5 `system_health_telemetry`
| Column        | Type          | Nullable | Notes |
| ------------- | ------------- | -------- | ----- |
| `id`          | `bigint`      | NO       | Auto-increment |
| `device_id`   | `varchar`     | YES      | |
| `log_level`   | `varchar`     | **NO**   | `INFO` \| `WARN` \| `ERROR` |
| `component`   | `varchar`     | **NO**   | Subsystem name |
| `message`     | `text`        | **NO**   | |
| `stack_trace` | `text`        | YES      | |
| `created_at`  | `timestamptz` | YES      | |

---

## 2. Supabase Storage

| Bucket        | App | Backend | Purpose |
| ------------- | --- | ------- | ------- |
| `leaf-images` | writes | reads | Captured leaf images for ML re-verification |

- **App upload:** after `/api/v1/scan`, upload the JPEG to
  `leaf-images/{device_id}/{epoch_ms}.jpg`, then store that path in
  `diagnostic_logs.image_storage_path` on INSERT.
- **Backend read:** gatekeeper worker downloads via `image_storage_path` from
  `leaf-images`. If the path is null/empty → **skip re-verification** (do not
  overwrite the edge values).
- Bucket name is configurable via `SUPABASE_STORAGE_BUCKET` (default
  `leaf-images`). `download_leaf_image()` tolerates a bare key, a
  bucket-prefixed key, or a full public/signed URL.

---

## 3. API Contracts

### 3.1 `POST /api/v1/scan` — Mobile → Backend
`multipart/form-data`:

| Field       | Type   | Required | Canonical | Backend now |
| ----------- | ------ | -------- | --------- | ----------- |
| `file`      | binary | YES      | JPEG      | ✅ |
| `latitude`  | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` |
| `longitude` | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` |

**Success (`200`):**
```jsonc
{
  "status": "success",
  "prediction": "Yellowish_Leaf",   // one of CLASSES (§6)
  "confidence": 0.87,               // 0.0–1.0, rounded 2dp
  "confidence_score": 0.87,         // duplicate of confidence
  "pest_type": "Whitefly",          // "Whitefly" | "None"
  "whitefly_count": 12,             // ⚠️ hardcoded — treat as estimate
  "action_protocol": "…",           // English guidance (= recommendation_en)
  "recommendation_en": "…",
  "recommendation_ur": "…",
  "latitude": 30.157,               // echoed
  "longitude": 71.524
}
```
**Error:** `{ "status": "error", "message": "<exception text>" }`

> `/scan` does **not** write to `diagnostic_logs`. The app INSERTs after
> receiving this response.

### 3.2 `POST /api/v1/supabase-webhook` — Supabase → Backend
```
Content-Type: application/json
```
Canonical envelope:
```jsonc
{
  "type": "INSERT",            // INSERT | UPDATE | DELETE
  "table": "diagnostic_logs",
  "schema": "public",          // key is "schema" — NOT "schema_name" (see §7)
  "record": { /* full diagnostic_logs row, all columns incl. nulls */ },
  "old_record": null           // populated on UPDATE/DELETE
}
```
**Responses:**
| Condition | Response |
| --------- | -------- |
| Queued | `{"status":"accepted","message":"Payload queued for system execution processing"}` |
| Duplicate `id` | `{"status":"ignored","message":"Duplicate event transaction already processing"}` |

**Gatekeeper trigger rule:** fires only when `record.confidence_score < 0.75`
(missing → defaults `1.0` → no trigger). Downloads image from
`record.image_storage_path` (bucket `leaf-images`), re-runs ML, UPDATEs **only**
`confidence_score` + `risk_level`. De-dup is in-memory (`processed_webhook_ids`),
lost on restart.

Current worker write-back ([main.py](main.py)):
```python
supabase_client.table("diagnostic_logs").update({
    "confidence_score": round(final_confidence, 2),
    "risk_level": derived_risk,        # canonical 4-level (§4): Fresh_Leaf→LOW, else by whitefly_count band
}).eq("id", row_id).execute()
```

### 3.3 `GET /api/v1/risk-metrics` — Dashboard/App → Backend
**Canonical response:**
```jsonc
{
  "temperature": 37.0,         // numeric
  "humidity": 42.0,            // numeric
  "wind_speed": 14.0,          // numeric
  "risk_level": "CRITICAL",    // canonical enum (§4)
  "alert_text_en": "…",
  "alert_text_ur": "…"
}
```
> ⚠️ Backend currently deviates: returns `"37°C"`/`"42%"`/`"14 km/h"` (strings)
> and `risk_level: "CRITICAL WHITEFLY RISK"` (non-canonical). See [§7](#7-backend-conformance-vs-canonical-contract).

### 3.4 `POST /api/v1/chat` — App → Backend
**Canonical request: JSON**
```jsonc
{ "message": "سفید مکھی کا علاج کیسے کریں", "language": "ur" }
```
**Response:** `{ "reply": "…urdu text…" }`
> ⚠️ Backend currently deviates: accepts `Form(...)` fields, not a JSON body.
> Keyword matching: `مکھی`/`سفید` → spray timing; `پانی`/`آبپاشی` → irrigation;
> else → generic inspection message.

---

## 4. Risk Level Enum (Canonical)

> All components use exactly these values — **uppercase, no spaces.**

| Value      | Meaning                          | Whitefly count band |
| ---------- | -------------------------------- | ------------------- |
| `LOW`      | Healthy / below threshold        | 0–4 |
| `MEDIUM`   | Monitor; localized presence      | 5–8 |
| `HIGH`     | Action recommended               | 9–15 |
| `CRITICAL` | Outbreak; immediate mitigation   | 16+ |

- Backend gatekeeper worker must emit **only these four** values.
- DB column is unconstrained `varchar` — recommend adding a CHECK constraint.
- ✅ **Worker now conforms:** `derive_risk_level(whitefly_count)` maps to the
  bands above; `Fresh_Leaf` → `LOW`, otherwise by count. ⚠️ `/risk-metrics`
  still emits free text — see [§7](#7-backend-conformance-vs-canonical-contract).
- **Nuance:** the image model is a classifier and does not count whiteflies, so
  the worker derives risk from `record["whitefly_count"]` (app-supplied). Flagged
  for the next MASTER refresh.

---

## 5. Language Codes (Canonical)

| Language | Code  | Display |
| -------- | ----- | ------- |
| Urdu     | `ur`  | اردو |
| Punjabi  | `pa`  | پنجابی |
| Saraiki  | `skr` | سرائیکی |
| English  | `en`  | EN |

Used in `farmers_profiles.preferred_language` and `/chat` `language`. Default
`"ur"`. ❌ Never full names like `"URDU"`. (Backend only references `ur` today.)

---

## 6. ML Model Constants

### 6.1 Class labels (`CLASSES`, [main.py](main.py))
Raw model output strings — all components must use exactly these:
```
Fresh_Leaf                 → healthy,          pest_type = "None"
Leaf_Reddening             → disease present,  pest_type = "Whitefly"
Leaf_Spot_Bacterial_Blight → disease present,  pest_type = "Whitefly"
Yellowish_Leaf             → disease present,  pest_type = "Whitefly"
```

### 6.2 Confidence
Scale **0.0–1.0** always (never 0–100). Dashboard renders `round(score*100)+"%"`.
Gatekeeper threshold: re-verification triggers when `< 0.75`.

### 6.3 Model version
`Flee-v1.0.4-stb` — active row flagged via `model_deployments.is_active_fleet_model = true`.

---

## 7. Backend Conformance vs Canonical Contract

How `main.py` currently lines up with §1–§6.

### ✅ Conforms / fixed
- No `status` column referenced. *(Fixed — was a confirmed `PGRST204` crash on the
  `confidence<0.75` path, reproduced live 2026-06-01 with a test row at `0.60`;
  webhook still returned `200 OK` while the swallowed `except` dropped the write.)*
- Worker reads `image_storage_path` (was `image_url`).
- Worker scores the **real** downloaded image (was `torch.randn(...)` noise) and
  **skips** the write when `image_storage_path` is empty.
- Bucket name configurable via `SUPABASE_STORAGE_BUCKET` (default `leaf-images`).
- **§4** worker emits canonical 4-level `risk_level` via `derive_risk_level()`
  (`Fresh_Leaf`→`LOW`, else by `whitefly_count` band).
- **§3.2** webhook model aliases `schema` → `schema_name` (`populate_by_name=True`),
  so the real envelope key is parsed instead of silently defaulted.
- **§8** `MODEL_PATH` read from env (`.env`), no machine-specific absolute path in code.
- **CORS** `CORSMiddleware` configured (origins via `CORS_ALLOW_ORIGINS`, default `*` for dev).

### 🟠 Open backend deviations (cross-repo — coordinate before shipping)
| Ref | Canonical | Current `main.py` |
| --- | --------- | ----------------- |
| §3.3 | `risk-metrics` numeric fields + canonical `risk_level` | Strings (`"37°C"`) + `"CRITICAL WHITEFLY RISK"` |
| §3.4 | `/chat` accepts **JSON** body | Accepts `Form(...)` fields |
| §3.1 | `/scan` GPS `null` when unavailable | `latitude`/`longitude` default `0.0` |
| §7-text | `recommendation_en` = "Apply targeted mitigation spray in morning or evening." | "Apply targeted mitigation if pest status is confirmed." |

> ⚠️ These change the wire contract the app/dashboard may already depend on
> (§3.4 Form→JSON, §3.3 string→numeric, §3.1 `0.0`→`null`). Align the other repos
> (or bump both) rather than break silently — held until those are ready.

### 🟡 Known limitations / hygiene
- `/scan` `whitefly_count` hardcoded to `12` (estimate, not measured).
- `inference_time_ms` never produced by backend — app must supply on INSERT.
- All `diagnostic_logs` NOT-NULL fields (`district`, `whitefly_count`,
  `risk_level`, `confidence_score`, `inference_time_ms`) are the **app's**
  responsibility on INSERT; `/scan` does not insert.
- In-memory webhook de-dup lost on restart (no DB idempotency).
- No webhook signature verification.
- `.env` holds live Supabase URL + key — confirm gitignored; rotate if sensitive.

### Upstream blockers (other repos — context only, per MASTER §9)
- 🔴 App does not upload images to Storage yet → `image_storage_path` always null
  → gatekeeper always skips. *(This is why the bucket appears empty and the
  re-verification path can't be exercised end-to-end yet.)*
- 🔴 App hardcodes `confidence_score = 0.95` → `<0.75` branch never fires.
- 🔴 App fabricates `whitefly_count` / hardcodes `inference_time_ms = 150`.
- 🟠 App sends `preferred_language = "URDU"` (should be `"ur"`), `app_version "2.4"`.
- 🟠 Dashboard reads `scores.f1` (should be flat `f1_score`); handles only
  `CRITICAL` (should handle all 4 enum values).

---

## 8. Environment Variables (Backend `.env`)

| Variable                  | Example                          | Notes |
| ------------------------- | -------------------------------- | ----- |
| `SUPABASE_URL`            | `https://xxx.supabase.co`        | |
| `SUPABASE_KEY`            | `sb_publishable_…`               | anon/publishable key. Private-bucket Storage reads may need a service-role key |
| `SUPABASE_STORAGE_BUCKET` | `leaf-images`                    | Bucket for leaf images |
| `MODEL_PATH`              | `./models/cottonace_stub.pth`    | ⚠️ currently hardcoded absolute — move here |
| `NGROK_URL`               | `https://xxx.ngrok-free.dev`     | Update on each ngrok restart; must match Supabase webhook portal |
