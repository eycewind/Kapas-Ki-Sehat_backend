# MASTER-CONTRACTS.md — Kapas Ki Sehat (CottonAce)

> **Single source of truth** for all data contracts shared across:
> - `Kapas-Ki-Sehat` (Android / Kotlin)
> - `KapasKiSehat_Backend` (FastAPI / Python)
> - `KapasKiSehat_Dashboard` (Next.js / TypeScript)
>
> **Place a copy at the root of all three repos.** When a shared contract changes,
> update this file first, then reconcile each repo's local CONTRACTS.md from it.
>
> **Version:** 4 · **Last merged from all three repos:** 2026-06-03
> **Previous:** v3 (2026-06-02), v2, v1

---

## What changed since v3

- **Image-upload chain is fully verified live and CLOSED.** End-to-end test
  passed: app uploaded a real JPEG to `leaf-images`, inserted a `diagnostic_logs`
  row with real values + non-null `image_storage_path`, the backend gatekeeper
  fired on a sub-0.75 scan (confirmed in console: `[MLOPS LIVE] … mapped to
  Fresh_Leaf with 0.51 confidence`), and the dashboard reflected it. v2 issues
  #1–5 are done.
- **All three CONTRACTS.md were self-verified against live code (2026-06-03).**
  The app's stale "current code" prose is corrected; backend and dashboard
  confirmed line-by-line.
- **Three new findings surfaced** (see §10): an orphaned `main.py` in the
  dashboard repo, the Storage bucket MIME-type quirk, and `NGROK_URL` not being
  read by backend code.
- **Active work item is now solely real `whitefly_count`** (§11) — Part A is done.

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
│  Read-only. Realtime on 4 tables. Counts, map, telemetry, MLOps. │
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
| `district`           | `varchar`          | **NO**   | App      | Required. Currently hardcoded `"Multan Belt"` (app TODO) |
| `whitefly_count`     | `integer`          | **NO**   | App      | Required. Real value (see §11 — backend still stubs `12`) |
| `risk_level`         | `varchar`          | **NO**   | App      | Required. Canonical enum — §4 |
| `confidence_score`   | `numeric`          | **NO**   | App      | Required. Real `ScanResponse.confidence`, 0.0–1.0 |
| `inference_time_ms`  | `integer`          | **NO**   | App      | Required. Measured round-trip (includes network) |
| `image_storage_path` | `text`             | YES      | App      | Bare object key `{device_id}/{epoch_ms}.jpg` — no bucket prefix, no leading slash. Null if upload failed |
| `created_at`         | `timestamptz`      | YES      | Supabase | Auto |
| `latitude`           | `double precision` | YES      | App      | GPS. `null` when unavailable — **NOT `0.0`** |
| `longitude`          | `double precision` | YES      | App      | GPS. `null` when unavailable — **NOT `0.0`** |
| `agricultural_belt`  | `varchar`          | YES      | App      | Currently `null` (app TODO: derive from district) |

> ❌ NO `status` column. ❌ NO `image_url` column. Use `image_storage_path`.

### 1.2 `farmers_profiles`

| Column               | Type          | Nullable | Notes |
|----------------------|---------------|----------|-------|
| `id`                 | `uuid`        | NO       | PK |
| `device_id`          | `varchar`     | **NO**   | Unique device identity (SHA-256 hash of ANDROID_ID + salt) |
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

> Dashboard reads the most recent 10 rows for the live telemetry console. No
> component writes to this table yet — populating it is a future task.

---

## 2. Supabase Storage

| Bucket        | App    | Backend | Purpose | Visibility |
|---------------|--------|---------|---------|------------|
| `leaf-images` | writes | reads   | Captured leaf images for ML re-verification | **Private** |

- **Object path format (FROZEN):** `{device_id}/{epoch_ms}.jpg` — a **bare object
  key**, no bucket prefix, no leading slash.
- **MIME restriction:** the bucket allows `image/*`. ⚠️ Do **not** narrow this to
  `image/jpeg` — the app's `supabase-kt` Storage client uploads `ByteArray` as
  `application/octet-stream`, which only `image/*` (wildcard) accepts. Narrowing
  it would silently break uploads.
- **App:** uploads after `/api/v1/scan`; stores the bare key in
  `image_storage_path`. Upload is non-fatal — on failure it logs WARN and sends
  `image_storage_path = null`.
- **Backend:** `download_leaf_image()` resolves via `_storage_client`. Since the
  bucket is **private**, the backend **must** use the service key — set
  `SUPABASE_SERVICE_KEY` (see §8). If `image_storage_path` is null/empty → **skip
  re-verification** (don't overwrite edge values).
- Bucket name configurable via `SUPABASE_STORAGE_BUCKET` (default `leaf-images`).

---

## 3. API Contracts

### 3.1 `POST /api/v1/scan` — Mobile → Backend
`multipart/form-data`:

| Field       | Type   | Required | Canonical | Backend now |
|-------------|--------|----------|-----------|-------------|
| `file`      | binary | YES      | JPEG, `filename="scan_{epochMillis}.jpg"` | ✅ |
| `latitude`  | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` (held — §11) |
| `longitude` | float  | NO       | `null` when unavailable | ⚠️ defaults `0.0` (held — §11) |

> Note: the app already omits lat/lon when GPS is unavailable; the `0.0` default
> is the backend's own `/scan` handling/logging, not what lands in the DB.

**Success (`200`):**
```jsonc
{
  "status": "success",
  "prediction": "Yellowish_Leaf",   // one of CLASSES (§6)
  "confidence": 0.87,               // 0.0–1.0, rounded 2dp
  "confidence_score": 0.87,         // duplicate of confidence
  "pest_type": "Whitefly",          // "Whitefly" | "None"
  "whitefly_count": 12,             // ⚠️ HARDCODED STUB — the v4 work item (§11)
  "action_protocol": "…",           // English (== recommendation_en)
  "recommendation_en": "…",         // ⚠️ wording differs from §7 (held — §11)
  "recommendation_ur": "…",
  "latitude": 30.157,               // echoed
  "longitude": 71.524
}
```
**Error:** `{ "status": "error", "message": "<text>" }`

**App `ScanResponse`** deserializes `status`, `prediction`, `confidence`,
`confidence_score`, `pest_type`, `whitefly_count`, `recommendation_en`,
`recommendation_ur`, all with safe defaults; `ignoreUnknownKeys = true`.

> `/scan` does **not** write `diagnostic_logs`. The app INSERTs after the response.

### 3.2 `POST /api/v1/supabase-webhook` — Supabase → Backend
```jsonc
{
  "type": "INSERT",            // INSERT | UPDATE | DELETE
  "table": "diagnostic_logs",
  "schema": "public",          // ✅ aliased: Pydantic maps "schema" → schema_name
  "record": { /* full diagnostic_logs row, all columns incl. nulls */ },
  "old_record": null
}
```
**Responses:**
| Condition | Response |
|-----------|----------|
| Queued | `{"status":"accepted","message":"Payload queued for system execution processing"}` |
| Duplicate `id` | `{"status":"ignored","message":"Duplicate event transaction already processing"}` |

**Gatekeeper trigger:** fires only when `record.confidence_score < 0.75` (missing
→ defaults `1.0` → no trigger). Downloads image, re-runs ML, UPDATEs **only**
`confidence_score` + `risk_level`. ✅ Verified firing live 2026-06-03. De-dup is
in-memory, lost on restart.

> ⚠️ The fix for the `schema`/`schema_name` alias lives in the **backend** repo's
> `main.py`. A **stale duplicate `main.py` exists in the dashboard repo** that
> still has the old `schema_name` bug — see §10 #D1. That copy is orphaned and
> should be deleted, not fixed.

### 3.3 `GET /api/v1/risk-metrics` — Dashboard/App → Backend ✅ conforms
```jsonc
{
  "district": "MULTAN",
  "temperature": 37.0, "humidity": 42.0, "wind_speed": 14.0,  // numeric
  "risk_level": "CRITICAL",    // canonical enum (§4)
  "alert_text_en": "…", "alert_text_ur": "…"
}
```
All values are stubs until wired to real weather/telemetry. Not yet consumed by
app or dashboard.

### 3.4 `POST /api/v1/chat` — App → Backend ✅ conforms
**Request (JSON):** `{ "message": "…", "language": "ur" }`
**Response:** `{ "reply": "…urdu text…" }`
Keyword matching: `مکھی`/`سفید` → spray timing; `پانی`/`آبپاشی` → irrigation;
else → generic inspection. App Expert screen is a static stub, not yet wired.

---

## 4. Risk Level Enum (Canonical)

> All components use exactly these values — **uppercase, no spaces.**

| Value      | Meaning                          | Whitefly count band | Marker color |
|------------|----------------------------------|---------------------|--------------|
| `LOW`      | Healthy / below threshold        | 0–4                 | `#6BE675` green |
| `MEDIUM`   | Monitor; localized presence      | 5–8                 | `#F4B740` amber |
| `HIGH`     | Action recommended               | 9–15                | `#F58B40` orange |
| `CRITICAL` | Outbreak; immediate mitigation   | 16+                 | `#F45B5B` red |

Unknown / non-canonical → gray `#9CA3AF` (dashboard).

**Derivation rule (shared):** `derive_risk_level(whitefly_count)` maps to the
bands above; `Fresh_Leaf` (healthy) → `LOW`.

- App: ✅ `deriveRiskLevel(whiteflyCount)` emits all four; verified live.
- Backend: ✅ gatekeeper uses `derive_risk_level()`; `/risk-metrics` canonical.
- Dashboard: ✅ all four color-coded; `=== 'CRITICAL'` filter is correct only for
  the single "Critical Outbreak Warnings" KPI.
- DB: `risk_level varchar` unconstrained — recommend a CHECK constraint.

> ⚠️ **Live consequence (see §11):** because `whitefly_count` is hardcoded to `12`
> by the backend, `derive_risk_level` always returns `HIGH` for any pest and `LOW`
> for healthy. Confirmed in live `diagnostic_logs` data (rows show only HIGH at
> count 12, LOW at count 0). `MEDIUM`/`CRITICAL` cannot occur until real counting
> lands. The enum is correctly implemented everywhere but starved of varied input.

---

## 5. Language Codes (Canonical)

| Language | Code  | `AppLanguage` enum | Display |
|----------|-------|--------------------|---------|
| Urdu     | `ur`  | `URDU` (default)   | اردو    |
| Punjabi  | `pa`  | `PUNJABI`          | پنجابی  |
| Saraiki  | `skr` | `SARAIKI`          | سرائیکی |
| English  | `en`  | `ENGLISH`          | EN      |

> ✅ Use **codes** (`ur/pa/skr/en`) on the wire. App sends `"ur"` (✅), currently
> hardcoded rather than tracking the live UI selection (app TODO). ❌ Never `"URDU"`.

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
- **The model is a classifier** — it does NOT count whiteflies. See §11.

---

## 7. Recommendation / Action Protocol

Returned by `/api/v1/scan` as `recommendation_ur` / `recommendation_en`:

| Condition | `recommendation_ur` | `recommendation_en` (canonical) |
|-----------|---------------------|---------------------------------|
| Whitefly detected | سفید مکھی کے تدارک کے لیے متعلقہ اسپرے صبح یا شام کے وقت کریں۔ | Apply targeted mitigation spray in morning or evening. |
| Healthy | کپاس کی فصل صحت مند ہے۔ کسی اسپرے کی ضرورت نہیں ہے۔ | Crop is healthy. No spray required. |

> ⚠️ Backend `/scan` currently returns `"Apply targeted mitigation if pest status
> is confirmed."` — differs from canonical. Held (touches `/scan`; bundle with §11).

---

## 8. Environment Variables

### 8.1 Supabase key format — RECONCILED (read before editing any `.env`)

Supabase projects support **two coexisting key systems**: legacy JWT keys
(`anon` / `service_role`, both `eyJh…`) and newer keys (`sb_publishable_…` /
`sb_secret_…`). They work side by side.

| Component | Key | Format | Why |
|-----------|-----|--------|-----|
| **App** | anon | **JWT `eyJh…`** | The Kotlin Storage module **rejects** `sb_publishable_…`. JWT anon required. |
| **Dashboard** | anon | **JWT `eyJh…`** | Browser-exposed; same anon key as app. |
| **Backend (DB)** | anon | JWT `eyJh…` | Standardize on the same anon key across all three. |
| **Backend (private Storage reads)** | service | `service_role` JWT / `sb_secret_…` | **Required** — `leaf-images` is private. Set `SUPABASE_SERVICE_KEY`. |

> ⚠️ Backend `.env` currently still lists `SUPABASE_KEY` as `sb_publishable_…`
> (§10 #B1). Switch it to the JWT anon key. Do NOT "fix" the app/dashboard to use
> `sb_publishable_…` — it breaks Storage uploads.

### 8.2 Backend (`.env`)
| Variable                  | Example                       | Notes |
|---------------------------|-------------------------------|-------|
| `SUPABASE_URL`            | `https://xxx.supabase.co`     | |
| `SUPABASE_KEY`            | JWT `eyJh…` (anon)            | DB + public Storage. **Switch from `sb_publishable_` per §8.1** |
| `SUPABASE_SERVICE_KEY`    | `service_role` JWT / `sb_secret_…` | **Required** for private `leaf-images` reads |
| `SUPABASE_STORAGE_BUCKET` | `leaf-images`                 | |
| `MODEL_PATH`              | machine-specific path         | Set in local `.env` |
| `NGROK_URL`               | `https://xxx.ngrok-free.dev`  | **NOT read by backend code.** Manual only: paste into the Supabase webhook portal after each ngrok restart |
| `CORS_ALLOW_ORIGINS`      | `*` dev / explicit origin prod | ✅ CORS middleware configured |

### 8.3 Dashboard (`.env.local`)
| Variable                        | Notes |
|---------------------------------|-------|
| `NEXT_PUBLIC_SUPABASE_URL`      | Must match backend |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | JWT anon key (§8.1); browser-exposed → relies on RLS |

### 8.4 Android app (`.env` via Secrets Gradle plugin → `BuildConfig`)
| Variable             | Notes |
|----------------------|-------|
| `BACKEND_BASE_URL`   | ✅ externalized; **host only**, no path/key. Rotate ngrok here |
| `SUPABASE_URL`       | ✅ externalized |
| `SUPABASE_ANON_KEY`  | ✅ externalized; **JWT format required** (§8.1) |

> ⚠️ `.env` lines must be `KEY=value` with no duplicated key prefix. A doubled
> `BACKEND_BASE_URL=BACKEND_BASE_URL=https://…` line caused a URL-parse crash
> (resolved 2026-06-03). Rebuild after editing — Secrets values bake into
> `BuildConfig` at compile time.

---

## 9. Cross-Repo Conformance Matrix (as of 2026-06-03, v4)

| Contract point | App | Backend | Dashboard |
|----------------|-----|---------|-----------|
| No `status` / `image_url` column | ✅ | ✅ | ✅ |
| `model_deployments` flat score columns | n/a | ✅ | ✅ |
| Webhook `schema` key | n/a | ✅ aliased | ⚠️ orphaned stale `main.py` (§10 #D1) |
| Risk enum 4-level implemented | ✅ | ✅ | ✅ |
| Risk enum receives varied input | 🔴 starved (whitefly=12) | 🔴 source of stub | 🔴 shows only HIGH/LOW |
| `/risk-metrics` numeric + canonical | not consumed | ✅ | not consumed |
| `/chat` JSON body | not consumed | ✅ | not consumed |
| GPS `null` not `0.0` | ✅ | 🟠 held (`/scan`) | ✅ |
| Image upload to Storage | ✅ verified live | ✅ verified live | n/a (optional) |
| Gatekeeper re-verification | n/a | ✅ verified firing | reflects updates |
| Real `confidence_score` | ✅ | ✅ | ✅ |
| Real `whitefly_count` | ✅ syncs what it gets | 🔴 hardcodes 12 | reads value |
| Real `inference_time_ms` | ✅ measured | n/a | n/a |
| `preferred_language` code `ur` | ✅ | references `ur` | n/a |
| `app_version` = gradle version | ✅ | n/a | n/a |
| Config externalized | ✅ | ✅ | ✅ |
| Supabase key format (JWT) | ✅ | ⚠️ `.env` lists `sb_publishable_` (§10 #B1) | ✅ |

Legend: ✅ conforms · 🟠 open, non-breaking · 🔴 open, blocks correct behavior

---

## 10. Remaining Issues (consolidated)

| # | Sev | Component | Issue |
|---|-----|-----------|-------|
| W1 | 🔴 | Backend | `/scan` `whitefly_count` hardcoded `12` → risk always HIGH/LOW. **v4 work item (§11)** |
| D1 | 🟠 | Dashboard | Orphaned stale `main.py` in dashboard repo (still has `schema_name` bug). **Delete it** — the real backend is in `KapasKiSehat_Backend`; this copy is dead and misleads contract syncs |
| B1 | 🟠 | Backend | `.env` `SUPABASE_KEY` should be JWT anon, not `sb_publishable_` (§8.1) |
| H1 | 🟠 | Backend | `/scan` GPS defaults `0.0` — change to `null` (held; bundle with §11) |
| H2 | 🟠 | Backend | `recommendation_en` wording differs from §7 (held; bundle with §11) |
| A1 | 🟡 | App | `agricultural_belt` synced as `null` — derive from district |
| A2 | 🟡 | App | `district` hardcoded `"Multan Belt"` — derive from GPS reverse-geocode |
| A3 | 🟡 | App | `preferred_language` correct code but hardcoded; track live UI selection |
| A4 | 🟡 | App | Home weather + Expert chat are stubs — wire to `/risk-metrics` + `/chat` |
| X1 | 🟡 | Backend | In-memory webhook dedup lost on restart; no webhook signature check |
| X2 | 🟡 | Dashboard | Zod runtime validation deferred (would warn on stubbed rows until real data) |
| X3 | 🟡 | All | `risk_level` has no DB CHECK constraint |
| X4 | 🟡 | All | Confirm `.env` files gitignored; rotate any committed credentials |

---

## 11. ▶ CURRENT CROSS-REPO WORK ITEM (v4): Real `whitefly_count`

**Part A (image-upload chain) is DONE and verified — no longer the work item.**

**Why this is next:** the app faithfully syncs whatever `whitefly_count` it
receives, but the backend hardcodes `12`. Since risk derives from the count,
**every pest scan becomes HIGH and every healthy scan LOW** — `MEDIUM`/`CRITICAL`
never occur. This is confirmed in live data. The 4-level enum all three repos
implemented is functionally binary until this is fixed. Highest-value correctness
item remaining.

### The contract decision to make FIRST (do not skip)

The current model is a *classifier* that cannot count. Pick ONE approach and
record it in this file before coding:

- **Option A — Add a counting model.** A detection/counting model (or second
  inference pass) yields a real integer count. Most accurate, most work.
- **Option B — Derive count/bands from classifier confidence + class.** Map
  `(class, confidence)` to a representative count or directly to a risk band.
  Cheaper, approximate, keeps the existing model.
- **Option C — Decouple risk from count.** Make `risk_level` a function of
  `(pest_type, confidence)`; keep `whitefly_count` as a separate metric. Cleanest
  conceptually but changes the §4 derivation rule all three repos depend on.

> Whichever is chosen, if it changes §4's derivation rule it becomes a MASTER
> revision. **Decide here, write it into §4, then propagate** — no repo improvises.

### Frozen contracts while this is worked

- `risk_level` enum values + bands in §4 stay as-is **unless Option C is chosen**,
  in which case §4 is rewritten first and all three repos update together.
- `diagnostic_logs` schema unchanged — `whitefly_count` stays `integer NOT NULL`.
- `/scan` response keeps `whitefly_count` as an integer field regardless of option.

### Guardrails per repo

- **Backend chat (primary):** replace the hardcoded `12`. For Option A, isolate
  counting so `/scan`'s response shape is unchanged. Do NOT alter the webhook
  handler or `download_leaf_image()`. You MAY bundle the held `/scan` cleanups
  (GPS `0.0`→`null` [H1], `recommendation_en` wording [H2]) since you're already
  in `/scan` — but call them out so app/dashboard expect the change.
- **App chat:** no change for Option A/B (already syncs the real value). For
  Option C, update `deriveRiskLevel` only after §4 is rewritten. Never re-introduce
  a hardcoded count.
- **Dashboard chat:** no change. Popup already shows `whitefly_count`; it will
  start showing varied values. Don't hardcode any expected range.

### Definition of done

Real (or properly-derived) `whitefly_count` flows end-to-end, and a set of test
scans produces a spread across at least three of the four risk levels, visible as
differently-colored markers on the dashboard. Then cut MASTER v5.

### Side cleanup (independent, safe to do anytime)

- **Delete the orphaned `main.py` from the dashboard repo (#D1).** It's dead code
  with a stale bug; removing it prevents accidental deployment and stops it
  polluting future contract verification.
- **Switch backend `.env` `SUPABASE_KEY` to the JWT anon key (#B1).**

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
- [ ] Storage bucket MIME stays `image/*` (not `image/jpeg`)
- [ ] Supabase keys are **JWT format** for the public surface (§8.1)
- [ ] Backend URL in app is host-only, no doubled key prefix in `.env`
- [ ] If `whitefly_count` derivation changed, §4 updated first, then all three repos