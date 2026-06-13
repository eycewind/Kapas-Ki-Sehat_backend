# CONTRACTS.md — KapasKiSehat_Backend (working source of truth)

> **Scope:** The backend's working source of truth for the data contracts it
> participates in: Supabase DB + Storage, webhooks, `/api/v1/*` endpoints.
> Tracks both the **canonical contract** and where `main.py` conforms or deviates.
>
> **Provenance:** Synced **from** `MASTER-CONTRACTS.md` v4 (last merged
> **2026-06-03**). When MASTER is refreshed, re-sync this file from it.
> Do not treat MASTER as live truth on its own — **this file** governs backend
> changes.
> **Last verified against `main.py`:** 2026-06-03 (line-by-line).

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
          ✅ Verified firing live 2026-06-03
                        │ Supabase Realtime
                        ▼
Next.js dashboard (read-only): counts, map, telemetry, MLOps
```

**Ownership rule:** the app owns all INSERTs. The backend only UPDATEs
`confidence_score` + `risk_level` on the gatekeeper path. Dashboard is read-only.

---

## 1. Supabase Table Schemas

### 1.1 `diagnostic_logs`

| Column               | Type               | Nullable | Owner    | Notes |
|----------------------|--------------------|----------|----------|-------|
| `id`                 | `uuid`             | NO       | Supabase | PK, auto-generated |
| `device_id`          | `varchar`          | YES      | App      | FK → `farmers_profiles.device_id` (`diagnostic_logs_device_id_fkey`) |
| `timestamp`          | `timestamptz`      | YES      | App      | Client event time (ISO-8601 UTC) |
| `district`           | `varchar`          | **NO**   | App      | Required. Currently hardcoded `"Multan Belt"` (app TODO) |
| `whitefly_count`     | `integer`          | **NO**   | App      | Required. App syncs what it gets; **backend stubs `12`** (§11 work item) |
| `risk_level`         | `varchar`          | **NO**   | App      | Required. Canonical enum — §4 |
| `confidence_score`   | `numeric`          | **NO**   | App      | Required. Real `ScanResponse.confidence`, 0.0–1.0 |
| `inference_time_ms`  | `integer`          | **NO**   | App      | Required. Measured round-trip (includes network) |
| `image_storage_path` | `text`             | YES      | App      | Bare object key `{device_id}/{epoch_ms}.jpg`. `null` if upload failed (non-fatal) |
| `created_at`         | `timestamptz`      | YES      | Supabase | Auto |
| `latitude`           | `double precision` | YES      | App      | GPS. `null` when unavailable — **NOT `0.0`** |
| `longitude`          | `double precision` | YES      | App      | GPS. `null` when unavailable — **NOT `0.0`** |
| `agricultural_belt`  | `varchar`          | YES      | App      | Currently `null` (app TODO: derive from district) |

> ❌ NO `status` column. ❌ NO `image_url` column. Use `image_storage_path`.

### 1.2 `farmers_profiles`

| Column               | Type          | Nullable | Notes |
|----------------------|---------------|----------|-------|
| `id`                 | `uuid`        | NO       | PK |
| `device_id`          | `varchar`     | **NO**   | SHA-256 hash of ANDROID_ID + salt |
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
| `created_at`  | `timestamptz` | YES      | Dashboard reads most-recent 10 rows for live telemetry console |

---

## 2. Supabase Storage

| Bucket        | App    | Backend | Visibility |
|---------------|--------|---------|------------|
| `leaf-images` | writes | reads   | **Private** |

- **Object path (FROZEN):** `{device_id}/{epoch_ms}.jpg` — bare key, no bucket
  prefix, no leading slash.
- **MIME:** bucket allows `image/*`. ⚠️ Do **not** narrow to `image/jpeg` — the
  app's `supabase-kt` uploads `ByteArray` as `application/octet-stream`, which
  only the wildcard accepts. Narrowing silently breaks uploads.
- **App:** uploads after `/api/v1/scan`; stores bare key in `image_storage_path`.
  Upload is non-fatal — on failure logs WARN and sends `image_storage_path = null`.
- **Backend:** `_storage_client` downloads via `image_storage_path`. Bucket is
  **private → `SUPABASE_SERVICE_KEY` is required** (see §8). If path null/empty
  → skip re-verification; do not overwrite edge values.
- Bucket name configurable via `SUPABASE_STORAGE_BUCKET` (default `leaf-images`).

---

## 3. API Contracts

### 3.1 `POST /api/v1/scan` — Mobile → Backend
`multipart/form-data`

| Field       | Type   | Required | Canonical | Backend now |
|-------------|--------|----------|-----------|-------------|
| `file`      | binary | YES      | JPEG      | ✅ |
| `latitude`  | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` — held, bundle with §11 [H1] |
| `longitude` | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` — held, bundle with §11 [H1] |

> Note: the app already omits lat/lon when GPS unavailable; the `0.0` default
> only affects backend logging, not what lands in the DB.

**Success (`200`):**
```jsonc
{
  "status": "success",
  "prediction": "Yellowish_Leaf",   // one of CLASSES (§6)
  "confidence": 0.87,               // 0.0–1.0, rounded 2dp
  "confidence_score": 0.87,         // duplicate of confidence
  "pest_type": "Whitefly",          // "Whitefly" | "None"
  "whitefly_count": 12,             // ✅ derived via estimate_whitefly_count (§11 Option B)
  "action_protocol": "…",           // English (== recommendation_en)
  "recommendation_en": "…",         // English (§7)
  "recommendation_ur": "…",         // Urdu (§7)
  "recommendation_pa": "…",         // Punjabi (§7, verified)
  "recommendation_skr": "…",        // Saraiki (§7, verified)
  "latitude": 30.157,               // null when GPS unavailable
  "longitude": 71.524               // null when GPS unavailable
}
```
**Error:** `{ "status": "error", "message": "<text>" }`

App `ScanResponse` deserializes all fields with safe defaults; `ignoreUnknownKeys = true`.

> `/scan` does **not** write `diagnostic_logs`. The app INSERTs after the response.

### 3.2 `POST /api/v1/supabase-webhook` — Supabase → Backend

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

Trigger: `confidence_score < 0.75` (missing → `1.0` → no trigger). Updates **only**
`confidence_score` + `risk_level`. ✅ Verified firing live 2026-06-03. De-dup
in-memory, lost on restart.

> ⚠️ A **stale orphaned `main.py` exists in the dashboard repo** (still has the
> `schema_name` bug). That copy is dead — the real backend is here. Delete it from
> the dashboard repo; do not fix it.

### 3.3 `GET /api/v1/risk-metrics` ✅ conforms

```jsonc
{
  "district": "MULTAN",
  "temperature": 37.0, "humidity": 42.0, "wind_speed": 14.0,
  "risk_level": "CRITICAL",
  "alert_text_en": "…", "alert_text_ur": "…"
}
```
All values are stubs. Not yet consumed by app or dashboard.

### 3.4 `POST /api/v1/chat` ✅ conforms

**Request (JSON):** `{ "message": "…", "language": "ur" }`
**Response:** `{ "reply": "…urdu text…" }`
App Expert screen is a static stub, not yet wired.

---

## 4. Risk Level Enum (Canonical)

| Value      | Meaning                        | Count band | Marker |
|------------|--------------------------------|------------|--------|
| `LOW`      | Healthy / below threshold      | 0–4        | `#6BE675` |
| `MEDIUM`   | Monitor; localized presence    | 5–8        | `#F4B740` |
| `HIGH`     | Action recommended             | 9–15       | `#F58B40` |
| `CRITICAL` | Outbreak; immediate mitigation | 16+        | `#F45B5B` |

Unknown/non-canonical → gray `#9CA3AF` (dashboard).

**Derivation rule (shared):** `derive_risk_level(whitefly_count)` — `Fresh_Leaf`
→ `LOW`; else by count band.

- App ✅ · Backend gatekeeper ✅ · Dashboard ✅ — all implemented correctly.
- ✅ **All four bands now reachable:** `estimate_whitefly_count(class, confidence)`
  maps to 0/3/6/12/18, producing LOW/MEDIUM/HIGH/CRITICAL from `derive_risk_level()`.
- DB: `risk_level varchar` unconstrained — recommend a CHECK constraint.

> **If §11 Option C is chosen**, this derivation rule changes — update §4 in
> MASTER first, then propagate to all three repos.

---

## 5. Language Codes (Canonical)

| Language | Code  | `AppLanguage` enum | Display |
|----------|-------|--------------------|---------|
| Urdu     | `ur`  | `URDU` (default)   | اردو    |
| Punjabi  | `pa`  | `PUNJABI`          | پنجابی  |
| Saraiki  | `skr` | `SARAIKI`          | سرائیکی |
| English  | `en`  | `ENGLISH`          | EN      |

Use **codes** on the wire. App sends `"ur"` ✅ (hardcoded; tracking live UI
selection is an app TODO). Backend `ChatRequest.language` defaults `"ur"`.
❌ Never send `"URDU"`.

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
- **The model is a classifier — it does NOT count whiteflies.** See §11.

---

## 7. Recommendation / Action Protocol

`/api/v1/scan` returns recommendations in **four languages**:
`recommendation_en`, `recommendation_ur`, `recommendation_pa` (Punjabi),
`recommendation_skr` (Saraiki) — one set for each case.

**Whitefly detected:**
| Field | Value |
|-------|-------|
| `recommendation_en` | Apply targeted mitigation spray in morning or evening. |
| `recommendation_ur` | سفید مکھی کے تدارک کے لیے متعلقہ اسپرے صبح یا شام کے وقت کریں۔ |
| `recommendation_pa` | چٹی مکھی دے تدارک لئی متعلقہ سپرے سویرے یا شام دے ویلے کرو۔ |
| `recommendation_skr` | چٹی مکھی دے تدارک کیتے متعلقہ سپرے سویل یا شام دے ویلے کرو۔ |

**Healthy:**
| Field | Value |
|-------|-------|
| `recommendation_en` | Crop is healthy. No spray required. |
| `recommendation_ur` | کپاس کی فصل صحت مند ہے۔ کسی اسپرے کی ضرورت نہیں ہے۔ |
| `recommendation_pa` | کپاہ دی فصل صحت مند اے۔ کسے سپرے دی لوڑ نئیں اے۔ |
| `recommendation_skr` | کپاہ دی فصل صحت مند ہے۔ کہیں سپرے دی لوڑ کائنی۔ |

> ✅ All four languages are **verified native translations** (PA/SKR provided by a
> native speaker, 2026-06-03). The app selects the correct field per `AppLanguage`
> (§5). No placeholders remain.

---

## 8. Supabase Keys + Environment Variables

### 8.1 Key format — CRITICAL (read before editing any `.env`)

Two coexisting key systems exist in Supabase projects:

| Component | Key type | Required format | Why |
|-----------|----------|-----------------|-----|
| App (anon) | anon | **JWT `eyJh…`** | Kotlin Storage client **rejects** `sb_publishable_…` |
| Dashboard (anon) | anon | **JWT `eyJh…`** | Same anon key; browser-exposed |
| Backend `SUPABASE_KEY` (DB) | anon | **JWT `eyJh…`** | Standardize with app/dashboard |
| Backend `SUPABASE_SERVICE_KEY` (Storage) | service | JWT `service_role` or `sb_secret_…` | **Required** — bucket is private |

> ⚠️ [B1] Backend `.env` currently has `SUPABASE_KEY=sb_publishable_…` — this
> must be switched to the JWT anon key. Get it from Supabase dashboard →
> Project Settings → API → `anon` (JWT). **Manual step — cannot be automated.**

### 8.2 Backend (`.env`)

| Variable                  | Example / current                    | Notes |
|---------------------------|--------------------------------------|-------|
| `SUPABASE_URL`            | `https://xxx.supabase.co`            | ✅ |
| `SUPABASE_KEY`            | ⚠️ currently `sb_publishable_…`     | **[B1] Switch to JWT anon key** (`eyJh…`) |
| `SUPABASE_SERVICE_KEY`    | `service_role` JWT or `sb_secret_…` | **Required** for private bucket reads. Placeholder in `.env` |
| `SUPABASE_STORAGE_BUCKET` | `leaf-images`                        | ✅ |
| `MODEL_PATH`              | machine-specific path                | ✅ read from env |
| `NGROK_URL`               | `https://xxx.ngrok-free.dev`         | **NOT read by backend code.** Manual only: paste into Supabase webhook portal after each ngrok restart |
| `CORS_ALLOW_ORIGINS`      | `*` dev / explicit origin prod       | ✅ CORS middleware configured |

---

## 9. Backend Conformance

### ✅ Conforms / fixed (verified 2026-06-03)
| Item | Evidence |
|------|----------|
| No `status` / `image_url` column | PGRST204 confirmed + fixed; update dict has only `confidence_score` + `risk_level` |
| Worker reads `image_storage_path` | line 163 |
| Worker scores real image | lines 175-185; PIL + inference_transforms |
| Skip on empty `image_storage_path` | lines 169-171; early return |
| `_storage_client` uses service key when set | lines 95-99 |
| `SUPABASE_STORAGE_BUCKET` from env | line 81 |
| 4-level `risk_level` via `derive_risk_level()` | lines 144-156, 192-195; verified live |
| Webhook `schema` aliased | lines 133, 137: `Field(alias="schema")` + `populate_by_name=True` |
| `MODEL_PATH` from env | line 48 |
| CORS configured | lines 27-34; `CORS_ALLOW_ORIGINS` env var |
| `sys.stdout.reconfigure("utf-8")` | lines 19-20 |
| `/risk-metrics` numeric + canonical | lines 245-252: `37.0`, `"CRITICAL"` |
| `/chat` JSON body | lines 126-128 `ChatRequest`; line 319 |
| Gatekeeper verified firing live | 2026-06-03 console: `[MLOPS LIVE] … mapped to Fresh_Leaf with 0.51 confidence` |

### ⚠️ Outstanding backend items
| Ref | Item | Status |
|-----|------|--------|
| [W1] ✅ | `/scan` `whitefly_count` now derived via `estimate_whitefly_count(class, confidence)` — Option B; all 4 risk bands reachable | Fixed |
| [H1] ✅ | GPS `Form(None)` — sends `null` when unavailable, not `0.0` | Fixed |
| [H2] ✅ | `recommendation_en` = "Apply targeted mitigation spray in morning or evening." | Fixed |
| [B1] 🟠 | `SUPABASE_KEY` is JWT ✅ but is the **service_role** key, not anon. Bypasses RLS on DB calls. `SUPABASE_SERVICE_KEY` not yet set separately. Storage reads work in practice. Swap to anon JWT + set service key before enforcing RLS. | Manual `.env` edit; see §8.1 |
| [X1] 🟡 | In-memory dedup lost on restart; no webhook sig check | Hygiene |
| [X4] 🟡 | `.env` credentials gitignored + rotated | Hygiene |

---

## 10. Cross-Repo Conformance (MASTER v4, 2026-06-03)

| Contract point | App | Backend | Dashboard |
|----------------|-----|---------|-----------|
| No `status`/`image_url` | ✅ | ✅ | ✅ |
| `model_deployments` flat columns | n/a | ✅ | ✅ |
| Webhook `schema` key | n/a | ✅ | ⚠️ orphaned `main.py` in dashboard — delete it |
| Risk enum 4-level implemented | ✅ | ✅ | ✅ |
| Risk enum receives varied input | ✅ syncs real value | ✅ Option B — all 4 bands reachable | ✅ will show all 4 |
| `/risk-metrics` numeric + canonical | not consumed | ✅ | not consumed |
| `/chat` JSON body | not consumed | ✅ | not consumed |
| GPS `null` not `0.0` | ✅ | ✅ [H1] fixed | ✅ |
| Image upload + gatekeeper | ✅ verified live | ✅ verified live | reflects updates |
| Real `confidence_score` | ✅ | ✅ | ✅ |
| Real `whitefly_count` | ✅ syncs what it gets | ✅ Option B derived | reads value |
| Real `inference_time_ms` | ✅ | n/a | n/a |
| `preferred_language` code | ✅ | `ur` only | n/a |
| Config externalized | ✅ | ✅ | ✅ |
| Supabase key JWT format | ✅ | 🟠 [B1] still `sb_publishable_` | ✅ |

---

## 11. Current Work Item: Real `whitefly_count` [W1]

**Part A (image-upload chain) is DONE and verified live 2026-06-03.**

**Why this is next:** every pest scan hardcodes `whitefly_count=12` → risk always
`HIGH`. Every healthy scan → `LOW`. `MEDIUM`/`CRITICAL` are unreachable. The
4-level enum all three repos built is functionally binary until this is fixed.

### ✅ Decision: Option B — map `(class, confidence)` → representative count

No proper counting model available yet. Option B keeps the existing classifier,
derives a representative `whitefly_count` from `(predicted_class, confidence)`,
and feeds it into the unchanged `derive_risk_level()`. §4's derivation rule is
**not modified** — no MASTER §4 revision required.

**`estimate_whitefly_count(predicted_class, confidence)` mapping:**

| Condition | Count | → `derive_risk_level()` |
|-----------|-------|------------------------|
| `Fresh_Leaf` (any confidence) | `0` | `LOW` |
| Pest class, confidence ≥ 0.90 | `18` | `CRITICAL` |
| Pest class, confidence ≥ 0.75 | `12` | `HIGH` |
| Pest class, confidence ≥ 0.50 | `6` | `MEDIUM` |
| Pest class, confidence < 0.50 | `3` | `LOW` (weak/ambiguous detection) |

Note: the 0.75 boundary aligns with the gatekeeper threshold — anything the
backend would re-verify maps to `MEDIUM` or below, which is conceptually
appropriate. Replace with a real counting model (Option A) when available.

### What's bundled with [W1] once decided
Per MASTER §11 guardrails — do these **in the same `/scan` edit**, not separately:
- **[H1]** GPS `Form(0.0)` → `Form(None)` / `Optional[float] = None`
- **[H2]** `recommendation_en` wording → "Apply targeted mitigation spray in morning or evening."

Do NOT change the webhook handler or `download_leaf_image()`.

### Side cleanup (independent, safe now)
- **[B1]** Switch `SUPABASE_KEY` in `.env` to JWT anon key (manual — get from Supabase → Project Settings → API → anon JWT)
