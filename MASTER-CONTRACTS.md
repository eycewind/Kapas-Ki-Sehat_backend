# MASTER-CONTRACTS.md — Kapas Ki Sehat (CottonAce)

> **Single source of truth** for all data contracts shared across:
> - `Kapas-Ki-Sehat` (Android / Kotlin)
> - `KapasKiSehat_Backend` (FastAPI / Python)
> - `KapasKiSehat_Dashboard` (Next.js / TypeScript)
>
> **Place a copy at the root of all three repos.** When a shared contract changes,
> update this file first, then reconcile each repo's local CONTRACTS.md from it.
>
> **Version:** 2 · **Last merged from all three repos:** 2026-06-02
> **Previous:** v1 (2026-06-01)

---

## 0. System Architecture

```
┌─ Android App (Kotlin) ──────────────────────────────────────────┐
│  1. Capture image                                                │
│  2. POST /api/v1/scan → FastAPI (image + lat/lon)               │
│  3. Receive ScanResponse                                         │
│  4. Upload image to Supabase Storage bucket "leaf-images"       │
│     → store returned path as image_storage_path                 │
│  5. INSERT diagnostic_logs (ALL required fields, REAL values)    │
│  6. Upsert farmers_profiles                                      │
└──────────────────────────────────────────────────────────────────┘
         │ Supabase webhook on INSERT
         ▼
┌─ FastAPI Backend ────────────────────────────────────────────────┐
│  POST /api/v1/supabase-webhook                                   │
│  → if confidence_score < 0.75:                                   │
│      download image from Storage (image_storage_path)            │
│      re-run ML (Flee-v1.0.4-stb)                                 │
│      UPDATE diagnostic_logs (confidence_score, risk_level only)  │
└──────────────────────────────────────────────────────────────────┘
         │ Supabase Realtime
         ▼
┌─ Next.js Dashboard ──────────────────────────────────────────────┐
│  Read-only. Realtime on diagnostic_logs. Counts, map, MLOps.     │
└──────────────────────────────────────────────────────────────────┘
```

**Ownership rule:** the **app** owns all INSERTs into `diagnostic_logs` and
`farmers_profiles`. The **backend** only ever UPDATEs `confidence_score` +
`risk_level` on the gatekeeper path. The **dashboard** is strictly read-only.

---

## 1. Supabase Table Schemas

Schema is managed manually via the Supabase SQL Editor. No component owns
migrations; all must conform.

### 1.1 `diagnostic_logs`
A new row INSERT fires the backend webhook.

| Column               | Type               | Nullable | Owner    | Notes |
|----------------------|--------------------|----------|----------|-------|
| `id`                 | `uuid`             | NO       | Supabase | PK, auto-generated |
| `device_id`          | `varchar`          | YES      | App      | FK → `farmers_profiles.device_id` |
| `timestamp`          | `timestamptz`      | YES      | App      | Client event time (ISO-8601 UTC) |
| `district`           | `varchar`          | **NO**   | App      | Required |
| `whitefly_count`     | `integer`          | **NO**   | App      | Required. Real value from ML response |
| `risk_level`         | `varchar`          | **NO**   | App      | Required. Canonical enum — §4 |
| `confidence_score`   | `numeric`          | **NO**   | App      | Required. Real `ScanResponse.confidence`, 0.0–1.0 |
| `inference_time_ms`  | `integer`          | **NO**   | App      | Required. Actual measured duration |
| `image_storage_path` | `text`             | YES      | App      | Object path in bucket `leaf-images` (§2) |
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
| `f1_score`              | `numeric`     | **NO**   | **Flat column** — NOT nested `scores.f1` |
| `precision_score`       | `numeric`     | **NO**   | **Flat column** — NOT `precision` |
| `recall_score`          | `numeric`     | **NO**   | **Flat column** — NOT `recall` |
| `is_active_fleet_model` | `boolean`     | YES      | Only one row `true` at a time |

### 1.4 `harvested_images_pool`

| Column                   | Type          | Nullable | Notes |
|--------------------------|---------------|----------|-------|
| `id`                     | `uuid`        | NO       | PK |
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

- **App upload:** after `/api/v1/scan`, upload the JPEG, then store the resulting
  object path in `diagnostic_logs.image_storage_path` on INSERT.
- **Backend read:** gatekeeper downloads via `image_storage_path`. If null/empty
  → **skip re-verification** (do not overwrite edge values).
- Bucket name configurable via `SUPABASE_STORAGE_BUCKET` (default `leaf-images`).
  `download_leaf_image()` tolerates a bare key, a bucket-prefixed key, or a full
  public/signed URL.

> **This chain is the current focus — see §11 for the coordinated work plan.**

---

## 3. API Contracts

### 3.1 `POST /api/v1/scan` — Mobile → Backend
`multipart/form-data`:

| Field       | Type   | Required | Canonical |
|-------------|--------|----------|-----------|
| `file`      | binary | YES      | JPEG, `filename="scan_{epochMillis}.jpg"` |
| `latitude`  | float  | NO       | `null` when unavailable — NOT `0.0` |
| `longitude` | float  | NO       | `null` when unavailable — NOT `0.0` |

**Success (`200`):**
```jsonc
{
  "status": "success",
  "prediction": "Yellowish_Leaf",   // one of CLASSES (§6)
  "confidence": 0.87,               // 0.0–1.0, rounded 2dp
  "confidence_score": 0.87,         // duplicate of confidence
  "pest_type": "Whitefly",          // "Whitefly" | "None"
  "whitefly_count": 12,             // ⚠️ backend hardcodes 12 — treat as estimate
  "action_protocol": "…",           // English (== recommendation_en)
  "recommendation_en": "…",
  "recommendation_ur": "…",
  "latitude": 30.157,               // echoed
  "longitude": 71.524
}
```
**Error:** `{ "status": "error", "message": "<text>" }`

> `/scan` does **not** write `diagnostic_logs`. The app INSERTs after the response.

### 3.2 `POST /api/v1/supabase-webhook` — Supabase → Backend
```jsonc
{
  "type": "INSERT",            // INSERT | UPDATE | DELETE
  "table": "diagnostic_logs",
  "schema": "public",          // key is "schema" NOT "schema_name"
  "record": { /* full diagnostic_logs row, all columns incl. nulls */ },
  "old_record": null           // populated on UPDATE/DELETE
}
```
**Responses:**
| Condition | Response |
|-----------|----------|
| Queued | `{"status":"accepted","message":"Payload queued for system execution processing"}` |
| Duplicate `id` | `{"status":"ignored","message":"Duplicate event transaction already processing"}` |

**Gatekeeper trigger:** fires only when `record.confidence_score < 0.75` (missing
→ defaults `1.0` → no trigger). Downloads image, re-runs ML, UPDATEs **only**
`confidence_score` + `risk_level`. De-dup is in-memory, lost on restart.

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
> ⚠️ **Backend currently deviates:** returns strings (`"37°C"`/`"42%"`/`"14 km/h"`)
> and `risk_level: "CRITICAL WHITEFLY RISK"`. Neither app nor dashboard consumes
> this endpoint yet, so the fix is safe to make on the backend side first.

### 3.4 `POST /api/v1/chat` — App → Backend
**Canonical request (JSON):**
```jsonc
{ "message": "سفید مکھی کا علاج کیسے کریں", "language": "ur" }
```
**Response:** `{ "reply": "…urdu text…" }`
> ⚠️ **Backend currently deviates:** accepts `Form(...)` fields, not JSON. Expert
> screen in the app is a static stub and does not call this yet — safe to align
> backend → JSON before the app wires it up.

---

## 4. Risk Level Enum (Canonical)

> All components use exactly these values — **uppercase, no spaces.**

| Value      | Meaning                          | Whitefly count band |
|------------|----------------------------------|---------------------|
| `LOW`      | Healthy / below threshold        | 0–4                 |
| `MEDIUM`   | Monitor; localized presence      | 5–8                 |
| `HIGH`     | Action recommended               | 9–15                |
| `CRITICAL` | Outbreak; immediate mitigation   | 16+                 |

**Derivation rule (shared):** `derive_risk_level(whitefly_count)` maps to the
bands above; `Fresh_Leaf` (healthy) → `LOW`. Because the image model is a
*classifier* and does not count whiteflies, risk is derived from the
app-supplied `whitefly_count`.

- App: must emit all four (currently only `CRITICAL`/`MEDIUM` — see §10).
- Backend: gatekeeper now conforms via `derive_risk_level()`. `/risk-metrics`
  still emits free text (§3.3).
- Dashboard: handles all four with color-coded markers; `=== 'CRITICAL'` filter
  is correct only for the single "Critical Outbreak Warnings" KPI.
- DB: `risk_level varchar` unconstrained — recommend a CHECK constraint.

**Marker colors (dashboard, `utils/types.ts`):** LOW `#6BE675`, MEDIUM `#F4B740`,
HIGH `#F58B40`, CRITICAL `#F45B5B`, unknown → gray `#9CA3AF`.

---

## 5. Language Codes (Canonical)

| Language | Code  | `AppLanguage` enum | Display |
|----------|-------|--------------------|---------|
| Urdu     | `ur`  | `URDU` (default)   | اردو    |
| Punjabi  | `pa`  | `PUNJABI`          | پنجابی  |
| Saraiki  | `skr` | `SARAIKI`          | سرائیکی |
| English  | `en`  | `ENGLISH`          | EN      |

> ✅ Use **codes** (`ur/pa/skr/en`) on the wire: `farmers_profiles.preferred_language`,
> `/chat` `language`. The app's `AppLanguage` enum may use full names internally
> for UI state, but must map to codes before sending. ❌ Never send `"URDU"`.

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
- **Confidence scale:** always `0.0–1.0`, never `0–100`. Dashboard renders `×100%`.

---

## 7. Recommendation / Action Protocol

Returned by `/api/v1/scan` as `recommendation_ur` / `recommendation_en`:

| Condition | `recommendation_ur` | `recommendation_en` |
|-----------|---------------------|---------------------|
| Whitefly detected | سفید مکھی کے تدارک کے لیے متعلقہ اسپرے صبح یا شام کے وقت کریں۔ | Apply targeted mitigation spray in morning or evening. |
| Healthy | کپاس کی فصل صحت مند ہے۔ کسی اسپرے کی ضرورت نہیں ہے۔ | Crop is healthy. No spray required. |

> ⚠️ Backend `recommendation_en` currently reads "Apply targeted mitigation if pest
> status is confirmed." — align to the canonical wording above.

---

## 8. Environment Variables

### Backend (`.env`)
| Variable                  | Example                       | Notes |
|---------------------------|-------------------------------|-------|
| `SUPABASE_URL`            | `https://xxx.supabase.co`     | |
| `SUPABASE_KEY`            | `sb_publishable_…`            | anon key; private-bucket reads may need service-role key |
| `SUPABASE_STORAGE_BUCKET` | `leaf-images`                 | |
| `MODEL_PATH`              | `./models/cottonace_stub.pth` | ✅ now read from env |
| `NGROK_URL`               | `https://xxx.ngrok-free.dev`  | Update each ngrok restart; must match Supabase webhook portal |
| `CORS_ALLOW_ORIGINS`      | `*` (dev)                     | ✅ CORS middleware now configured |

### Dashboard (`.env.local`)
| Variable                        | Notes |
|---------------------------------|-------|
| `NEXT_PUBLIC_SUPABASE_URL`      | Must match backend |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Same anon key (browser-exposed → relies on RLS) |

### Android app
| Constant           | Current location               | Fix |
|--------------------|--------------------------------|-----|
| Backend base URL   | `NetworkUtil.kt` hardcoded LAN IP | Move to `BuildConfig` / `local.properties` |
| Supabase URL + key | `CottonAceApplication.kt` hardcoded | Move to `local.properties` + Secrets plugin; rotate |

---

## 9. Cross-Repo Conformance Matrix

Current state of each shared contract across the three repos (as of 2026-06-02).

| Contract point | App | Backend | Dashboard |
|----------------|-----|---------|-----------|
| No `status` / `image_url` column | ✅ | ✅ fixed | ✅ fixed |
| `model_deployments` flat score columns | n/a | ✅ | ✅ fixed |
| Webhook `schema` key (not `schema_name`) | n/a | ✅ aliased | n/a |
| Risk enum 4-level | 🔴 emits only CRITICAL/MEDIUM | ✅ worker conforms | ✅ all 4 handled |
| `/risk-metrics` numeric + canonical risk | not consumed | 🟠 still strings | not consumed |
| `/chat` JSON body | not consumed | 🟠 still Form | not consumed |
| GPS `null` not `0.0` | 🟠 sends 0.0 | 🟠 defaults 0.0 | ✅ validates both |
| Image upload to Storage | 🔴 not implemented | ✅ ready to read | n/a |
| Real `confidence_score` | 🔴 hardcoded 0.95 | ✅ returns real | reads real |
| Real `whitefly_count` | 🔴 fabricated | 🟡 hardcodes 12 | reads value |
| Real `inference_time_ms` | 🔴 hardcoded 150 | n/a (app supplies) | n/a |
| `preferred_language` = `ur` | ✅ fixed | only `ur` referenced | n/a |
| `app_version` = gradle version | ✅ fixed | n/a | n/a |
| Error handling / robustness | ✅ round done | partial | ✅ round done |

Legend: ✅ conforms · 🟠 open, non-breaking · 🔴 open, blocks pipeline · 🟡 known limitation

---

## 10. Remaining Issues (consolidated)

| # | Sev | Component | Issue |
|---|-----|-----------|-------|
| 1 | 🔴 | App | No Storage upload → `image_storage_path` null → gatekeeper never runs |
| 2 | 🔴 | App | `confidence_score` hardcoded `0.95f` — use real `ScanResponse.confidence` |
| 3 | 🔴 | App | `whitefly_count` fabricated — extend `ScanResponse`, use real value |
| 4 | 🔴 | App | `inference_time_ms` hardcoded `150` — measure actual time |
| 5 | 🔴 | App | `DiagnosticLogPayload` missing `image_storage_path`, `latitude`, `longitude`, `agricultural_belt` |
| 6 | 🟠 | App | GPS defaults `0.0/0.0` — send `null` |
| 7 | 🟠 | App | Emits only `CRITICAL`/`MEDIUM` — add `LOW`/`HIGH` via whitefly bands |
| 8 | 🟡 | App | `diagnostic_logs` insert response not inspected (marks synced even on 0 rows) |
| 9 | 🟡 | App | Home weather + Expert chat hardcoded — wire to `/risk-metrics` and `/chat` |
| 10 | 🟠 | Backend | `/risk-metrics` returns strings + non-canonical `risk_level` |
| 11 | 🟠 | Backend | `/chat` accepts Form, not JSON |
| 12 | 🟠 | Backend | GPS defaults `0.0` in `/scan` |
| 13 | 🟡 | Backend | `recommendation_en` wording differs from §7 |
| 14 | 🟡 | Backend | `/scan` `whitefly_count` hardcoded `12` |
| 15 | 🟡 | Backend | In-memory dedup lost on restart; no webhook signature check |
| 16 | 🟠 | Dashboard | "Real-time Inference Sync" counts all rows (no date filter) |
| 17 | 🟡 | Dashboard | Telemetry stream still fabricated |
| 18 | 🟡 | Dashboard | Realtime only watches `diagnostic_logs` |
| 19 | 🟡 | All | Supabase credentials committed — rotate, gitignore, consider RLS review |

---

## 11. ▶ CURRENT CROSS-REPO WORK ITEM: The Image-Upload + Real-Data Chain

**Why this one:** it is the keystone. Until the app uploads images and writes real
values, the entire backend gatekeeper pipeline is dormant (issues #1–#5). The
backend side is already built and waiting. This single chain converts the system
from "looks healthy but verification never runs" to actually functioning
end-to-end.

**Repos involved:** App (primary), Backend (already ready), Dashboard (passive
consumer), plus one Supabase setup step.

### The agreed contract for this chain (freeze before coding)

These values are **fixed** for this work item. No repo may deviate without a
new MASTER revision:

1. **Bucket name:** `leaf-images` (matches backend default `SUPABASE_STORAGE_BUCKET`)
2. **Object path format:** `{device_id}/{epoch_ms}.jpg`
   - The app stores **exactly this** in `image_storage_path` — the bare object
     key, **without** the bucket name prefix and **without** a leading slash.
   - Rationale: backend `download_leaf_image()` tolerates several forms, but we
     standardize on the bare key to avoid ambiguity. Pick one, document it, stick to it.
3. **`ScanResponse` (app) must be extended** to deserialize at minimum:
   `status`, `pest_type`, `confidence`, `confidence_score`, `whitefly_count`,
   `recommendation_ur`, `recommendation_en`. All with safe defaults so a missing
   field never crashes.
4. **`DiagnosticLogPayload` (app) must add:** `image_storage_path`, `latitude`
   (nullable), `longitude` (nullable), `agricultural_belt`.
5. **Values written to `diagnostic_logs` must be real:**
   - `confidence_score` ← `ScanResponse.confidence` (0.0–1.0)
   - `whitefly_count` ← `ScanResponse.whitefly_count`
   - `inference_time_ms` ← measured round-trip (app clock around the `/scan` call is acceptable for now; document that it includes network time)
   - `risk_level` ← `derive_risk_level(whitefly_count)` using §4 bands

### Ordering — do these in sequence to avoid breakage

**Step 0 — Supabase (you, once, before any code):**
- Create the `leaf-images` bucket if it doesn't exist.
- Decide public vs private:
  - If **private**, the backend `SUPABASE_KEY` must be a **service-role key** (the
    anon key can't read private objects). Update backend `.env`.
  - If **public**, anon key suffices but anyone with the URL can read images.
- Add an RLS / storage policy allowing the app's anon key to **INSERT** (upload)
  to the bucket.
- ✅ Verify by manually uploading one file via the Supabase dashboard and
  confirming the backend can download it with its configured key.

**Step 1 — App: extend the DTOs (no behavior change yet):**
- Extend `ScanResponse` and `DiagnosticLogPayload` per the frozen contract above.
- This is non-breaking: adding fields with defaults doesn't change what's sent yet.
- ✅ Verify: app still compiles, existing scan flow still works.

**Step 2 — App: install Storage module + upload:**
- Add the `Storage` module to the Supabase client in `CottonAceApplication.kt`.
- After a successful `/scan`, upload the **real captured JPEG** (the file already
  carried via `SharedViewModel`, not the old mock path) to
  `leaf-images/{device_id}/{epoch_ms}.jpg`.
- Store that exact object key for the upcoming insert.
- ✅ Verify: a file appears in the bucket after a scan.

**Step 3 — App: write real values on INSERT:**
- Populate `image_storage_path`, real `confidence_score`, real `whitefly_count`,
  measured `inference_time_ms`, and `latitude`/`longitude` (null if no GPS).
- ✅ Verify: a new `diagnostic_logs` row has a non-null `image_storage_path` and
  realistic values.

**Step 4 — End-to-end gatekeeper test (all repos together):**
- Submit a scan whose `confidence_score < 0.75` (use a deliberately ambiguous
  leaf image, or temporarily lower the threshold in a test).
- ✅ Verify the backend webhook fires, downloads the image, re-runs ML, and
  UPDATEs `confidence_score` + `risk_level`.
- ✅ Verify the dashboard reflects the updated row via Realtime.

### Guardrails — what each chat must NOT do

- **App chat:** do not change the bucket name or path format. Do not start sending
  `latitude=0.0`; send `null`. Do not remove `ignoreUnknownKeys` (backend may add
  response fields later). Do not touch `risk_level` derivation bands — use §4.
- **Backend chat:** do **not** modify `/scan`, the webhook handler, or
  `download_leaf_image()` during this work item — the backend side is frozen and
  ready. If a real bug surfaces, flag it here for a MASTER revision rather than
  silently changing the read path. Do not change `SUPABASE_STORAGE_BUCKET` default.
- **Dashboard chat:** no changes required for this item. Do **not** add a hard
  dependency on `image_storage_path` being non-null (older rows have null). Treat
  it as optional when displaying.

### Definition of done

A scan taken on the phone results in: (1) an image in `leaf-images`, (2) a
`diagnostic_logs` row with real `confidence_score`/`whitefly_count`/
`inference_time_ms` and a non-null `image_storage_path`, (3) for a sub-0.75
confidence row, a backend gatekeeper UPDATE, and (4) the dashboard reflecting it
live. When all four hold, mark issues #1–#5 closed and cut MASTER v3.

---

## 12. Quick Sync Checklist

Before pushing changes that touch shared contracts:

- [ ] `diagnostic_logs` column names match §1.1 exactly
- [ ] `risk_level` ∈ `LOW / MEDIUM / HIGH / CRITICAL`
- [ ] `confidence_score` on `0.0–1.0` scale
- [ ] `preferred_language` uses codes from §5
- [ ] `model_deployments` scores read as flat `f1_score / precision_score / recall_score`
- [ ] No component sends `0.0` for missing GPS — use `null`
- [ ] `image_storage_path` is the bare object key `{device_id}/{epoch_ms}.jpg`
- [ ] Backend URL in app updated if ngrok restarted