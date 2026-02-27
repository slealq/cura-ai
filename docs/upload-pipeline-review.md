# Upload & Ingestion Pipeline — Architectural Review

## Executive Summary

- **The pipeline is well-designed for its intended scale** — fast ingest (file + PENDING record) in the API, heavy processing (thumbnails) deferred to Celery, folder assignment deferred to job completion.
- **The primary "hang" symptom** is caused by `fast_ingest()` performing synchronous PIL metadata computation + storage writes **inline in the HTTP request handler** for every file in a chunk (up to 15 files × 3 parallel chunks = 45 concurrent storage writes blocking the event loop or competing for I/O).
- **Folder assignment bugs** stem from a **race condition on `job.result` dictionary updates** — concurrent chunk uploads can overwrite each other's `image_ids` / `all_upload_ids` arrays, causing images to be silently dropped from folder assignment.
- **"No folder" uploads work correctly** at the data model level (images exist without FolderImage rows), but the UI's folder-centric design may make them hard to discover.
- **Duplicate detection** has an application-level check but relies on a DB unique constraint `(user_id, file_hash)` for true safety — however `fast_ingest()` doesn't catch the `IntegrityError`, meaning a constraint violation will surface as a 500 error.
- **Non-atomic storage + DB writes** mean a crash between `save_image()` and `db.flush()` orphans files in storage with no recovery mechanism.

---

## A. Current Architecture (As-Is)

### Pipeline Sequence

```
┌─────────────────────────────────────────────────────────────────────────┐
│ FRONTEND (Browser)                                                      │
│                                                                         │
│ 1. User selects files + folder → clicks "Upload"                       │
│ 2. startUpload() sets lock, shows toast, navigates to /images          │
│ 3. uploadChunked() splits files into chunks of 15                      │
│ 4. Chunk 1 sent sequentially (gets job_id), rest in parallel batches   │
│    of 3 via Promise.allSettled()                                       │
│ 5. Per-chunk progress callback updates toast: "Sending X/Y (Z%)"      │
│ 6. On completion: success toast + cache invalidation                   │
└──────────────────────┬──────────────────────────────────────────────────┘
                       │ POST /images/upload/batch (multipart/form-data)
                       │ ×N chunks, 5min timeout each
                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ BACKEND (FastAPI, uvicorn)                                              │
│                                                                         │
│ upload_images_batch() — api/images.py:75-234                           │
│   7.  Create Job(INGEST, RUNNING) on first chunk OR load existing      │
│   8.  For each file in chunk:                                          │
│       a. Read file bytes into memory (await file.read())               │
│       b. fast_ingest(): SHA-256 → dedup check → PIL metadata →        │
│          storage.save_image() → Image(PENDING) → db.flush()           │
│       c. db.commit() per file                                          │
│   9.  Merge image IDs into job.result dict                             │
│   10. Dispatch process_ingest_batch.delay(new_ids, user_id, job_id)   │
│   11. Count immediate completions (duplicates + failures)              │
│   12. If job complete: mark COMPLETED + folder assignment              │
│   13. Return { uploaded, failed, job_id }                              │
└──────────────────────┬──────────────────────────────────────────────────┘
                       │ Celery task dispatch via Redis
                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ CELERY WORKER (concurrency=1 on default queue)                          │
│                                                                         │
│ process_ingest_batch() — workers/tasks.py:330-457                      │
│   14. For each image_id:                                               │
│       a. Re-delivery guard: skip if status != PENDING                  │
│       b. Read file back from storage                                   │
│       c. Compute metadata if missing (width/height/phash)              │
│       d. Generate 3 thumbnails (200, 400, 800px via PIL)              │
│       e. Save thumbnails to storage (3 writes)                         │
│       f. Update Image → status=INGESTED, thumbnail URIs               │
│       g. db.commit()                                                   │
│       h. _finish_ingest_job_item() → atomic progress++                │
│   15. When progress >= total_items:                                    │
│       a. Count FAILED images → set job status                          │
│       b. _assign_folder_on_completion():                               │
│          - Get-or-create folder if new_folder_name                     │
│          - add_images_to_folder(folder_id, all_upload_ids)            │
│          - refresh_cover_image() + generate_cover_composite()         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ FRONTEND POLLING                                                        │
│                                                                         │
│ useJobNotifications() — 5s refetchInterval on /jobs                    │
│   16. Detects job status → COMPLETED                                   │
│   17. Invalidates ['folders'], ['images'], ['stats'] queries           │
│   18. Shows toast: "Upload completed"                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Source of Truth by Stage

| Stage | Source of Truth | Where |
|-------|----------------|-------|
| File selected | Browser `File[]` in UploadContext | Client memory |
| Upload in progress | `uploadingRef` + `state.isUploading` | Client state |
| Chunk sent to server | HTTP response with `uploaded[]` / `failed[]` | API response |
| File stored | Object in storage (local/Azure/S3) | Storage layer |
| Image record exists | `images` table, `status=PENDING` | PostgreSQL |
| Thumbnails generated | `images.thumbnail_uri_*`, `status=INGESTED` | PostgreSQL + storage |
| Folder assigned | `folder_images` junction table | PostgreSQL |
| Job progress | `jobs.progress` / `jobs.total_items` | PostgreSQL |
| Job complete | `jobs.status=COMPLETED` | PostgreSQL |

### Components & Communication

| Component | Protocol | Notes |
|-----------|----------|-------|
| Frontend → Backend | HTTP POST multipart, 5min timeout | Direct uvicorn, no reverse proxy |
| Backend → Storage | Sync (local) / `asyncio.to_thread` (Azure) / Sync (S3) | In HTTP request context |
| Backend → Celery | Redis (task dispatch via `.delay()`) | Fire-and-forget |
| Celery → Storage | Sync wrapped in `run_async()` | Per-thread event loop |
| Celery → DB | SQLAlchemy sync, per-task `SessionLocal()` | Separate pool |
| Frontend ← Backend | 5s polling on `/jobs` endpoint | TanStack Query |

---

## B. Failure Modes & Root Cause Hypotheses

### B1. Hanging Uploads

**Root cause 1: `fast_ingest()` does synchronous PIL + storage I/O inline in the HTTP handler**
- `image_service.py:172-177`: For each file, `compute_image_metadata()` opens PIL + computes phash, then `save_image()` writes to storage. For Azure, this uses `asyncio.to_thread()` but each upload is ~1-3s.
- With 15 files per chunk × up to 3 parallel chunks, the backend is doing 15 PIL opens + 15 storage writes per request. A single chunk takes **15-45 seconds** on Azure.
- **Evidence**: The 5-minute per-chunk timeout exists specifically because chunks are slow.

**Root cause 2: Celery concurrency=1 bottleneck**
- `docker-compose.yml:86`: `--concurrency=1` on the default worker. Each chunk dispatches one `process_ingest_batch` task, but they execute sequentially.
- 100 images across 7 chunks → 7 tasks, executed one at a time. Each task reads files back from storage + generates 3 thumbnails per image. Total processing: **minutes**.
- The upload HTTP request returns quickly, but the "hang" perception comes from the job never completing.

**Root cause 3: `file.read()` loads entire file into memory**
- `images.py:140`: `file_data = await file.read()` loads the complete file into the FastAPI process memory. With 15 large images (e.g. 10MB each), that's 150MB per chunk.
- 3 parallel chunks = 450MB in memory simultaneously on the uvicorn process.

**Root cause 4: DB commit per file (images.py:173)**
- Each file gets its own `db.commit()` within the chunk loop. This is correct for isolation but means the chunk request holds a DB session for the duration of all 15 files.

### B2. Folder Assignment Bugs

**Root cause 1: CRITICAL — `job.result` dictionary race condition**
- `images.py:186-193`: When updating `job.result`, the endpoint reads the current dict, appends new IDs, and writes back. With 3 parallel chunks hitting this code simultaneously:
  ```
  Chunk A reads job.result: image_ids=[1,2]
  Chunk B reads job.result: image_ids=[1,2]   (stale!)
  Chunk A writes: image_ids=[1,2,3,4]
  Chunk B writes: image_ids=[1,2,5,6]          (overwrites A's [3,4])
  ```
- **Result**: Images 3 and 4 are permanently lost from `all_upload_ids`. They exist in the DB but are never assigned to the folder.
- **No SELECT FOR UPDATE** is used. The default PostgreSQL READ COMMITTED isolation lets both chunks read the pre-update state.

**Root cause 2: Dual folder assignment paths**
- Both the API endpoint (`images.py:220-221`) and the Celery worker (`tasks.py:238`) call `_assign_folder_on_completion()`. Both paths can fire, wasting resources but not causing data issues (the function is idempotent).

**Root cause 3: `folder.image_count` denormalization race**
- `folder_service.py:155-160`: `image_count` is set to `COUNT(*) + added` without locking the row. Concurrent `add_images_to_folder` calls will compute stale counts, leading to `image_count` drift (displayed count != actual count).

### B3. "No Folder" Upload Behavior

**The data model supports folderless images.** Images exist independently; the `FolderImage` junction table is the only link. There is no `folder_id` on the `Image` model.

The UI upload page correctly shows "No folder (upload to library only)" as the default option (`upload/page.tsx:97`). The backend accepts `folder_id=None` and `new_folder_name=None` — it simply skips folder assignment.

**Potential confusion point**: `image_service.get_images()` has an `in_folder` filter parameter (`image_service.py:233-238`), which means images not in any folder can be queried separately. If a UI view filters to `in_folder=True`, folderless images become invisible.

### B4. Missing/Duplicate Images

**Duplicate detection is application-level with a DB safety net:**
- `fast_ingest()` checks `WHERE file_hash = X AND user_id = Y` before inserting.
- Migration 017 creates `UNIQUE(user_id, file_hash)` as a DB constraint.
- **Gap**: `fast_ingest()` doesn't catch `IntegrityError`. If two concurrent requests pass the application check, the second `db.flush()` will raise an unhandled `IntegrityError`, propagated as a 500 error for that file. The file is already written to storage at this point (orphaned).

**Non-atomic storage + DB writes:**
- `image_service.py:177`: `save_image()` writes to storage.
- `image_service.py:195-196`: `db.add(image)` + `db.flush()` writes to DB.
- If the process crashes between lines 177 and 196, the file is orphaned in storage with no DB record. There is no cleanup handler.

**Missing `_finish_ingest_job_item` call on re-delivery skip:**
- `tasks.py:374-379`: If image status != PENDING (re-delivery guard), the task skips it with `continue` — but does NOT call `_finish_ingest_job_item()`. This means re-delivered images that were already processed won't increment job progress.
- **Impact**: If a Celery task is re-delivered (worker crash + `task_acks_late=True`), the skipped images' progress is never counted, and the job hangs at `progress < total_items` forever.

---

## C. State Machine & Invariants

### Proposed Image Lifecycle State Machine

```
                          ┌──────────┐
        User drops files  │  (none)  │  Browser memory only
                          └─────┬────┘
                                │ fast_ingest(): save file + create row
                                ▼
                          ┌──────────┐
                          │ PENDING  │  File in storage, row in DB, no thumbnails
                          └─────┬────┘
                                │ process_ingest_batch: thumbnails + metadata
                                ▼
                          ┌──────────┐
                          │ INGESTED │  Thumbnails exist, visible in UI
                          └─────┬────┘
                                │ tag_image
                                ▼
                          ┌──────────┐
                          │  TAGGED  │
                          └─────┬────┘
                                │ describe_image
                                ▼
                          ┌───────────┐
                          │ DESCRIBED │
                          └─────┬─────┘
                                │ embed_image
                                ▼
                          ┌──────────┐
                          │ EMBEDDED │
                          └─────┬────┘
                                │ cluster_all_images
                                ▼
                          ┌───────────┐
                          │ CLUSTERED │
                          └───────────┘

    Any state ──(error)──→ FAILED (retryable)
```

### Transition Ownership & Atomicity

| Transition | Owner | Atomic? | Idempotent? | Notes |
|-----------|-------|---------|-------------|-------|
| (none) → PENDING | API handler via `fast_ingest()` | NO — storage write + DB flush are separate | NO — duplicate check is app-level, DB constraint is safety net | File can be orphaned |
| PENDING → INGESTED | Celery `process_ingest_batch` | Partial — thumbnails written separately, then single `db.commit()` | YES — re-delivery guard checks `status != PENDING` | **Bug: skipped images don't call `_finish_ingest_job_item()`** |
| INGESTED → TAGGED | Celery `tag_image` | YES — single DB commit | YES — can be re-tagged | Rate limited at 30/m |
| TAGGED → DESCRIBED | Celery `describe_image` | YES — single DB commit | YES — can be re-described | Rate limited at 30/m |
| DESCRIBED → EMBEDDED | Celery `embed_image` | YES — single DB commit | YES — can be re-embedded | Rate limited at 60/m |
| EMBEDDED → CLUSTERED | Celery `cluster_all_images` | YES — bulk update | YES — can be re-clustered | Runs on clustering queue |

### Proposed Invariants

1. **PENDING implies**: `storage.exists(object_key) == True` AND `Image row exists` AND `thumbnail_uri_* IS NULL`
2. **INGESTED implies**: All of PENDING + `thumbnail_uri_small IS NOT NULL` AND `thumbnail_uri_medium IS NOT NULL`
3. **For all non-FAILED images**: `storage.exists(object_key) == True` (no orphaned DB records)
4. **Folder assignment**: `FolderImage(folder_id, image_id)` exists implies `Image.id == image_id` exists (FK enforced)
5. **Images may have no folder**: `NOT EXISTS (SELECT 1 FROM folder_images WHERE image_id = X)` is a valid state; these images are discoverable via `/images?in_folder=false` or the "All Images" view
6. **Job completion**: `job.progress == job.total_items` implies `job.status IN (COMPLETED, FAILED)`
7. **job.result['all_upload_ids']** should contain **all** image IDs from **all** chunks (currently broken by race condition)

---

## D. Architectural Improvements

### P0 — Critical (Data Correctness)

**D1. Lock `job.result` updates with SELECT FOR UPDATE**

File: `backend/app/api/images.py:179-193`

The race on `job.result` is the most likely cause of folder assignment bugs. The fix:

```python
# images.py:179 — replace the plain query with a locked fetch
job = db.query(Job).with_for_update().filter(Job.id == job.id).first()
```

This serializes concurrent chunk uploads on the same job, ensuring `image_ids` and `all_upload_ids` arrays are never overwritten by a stale read. Cost: brief lock contention on concurrent chunks (milliseconds).

**D2. Handle `IntegrityError` in `fast_ingest()` for duplicate detection**

File: `backend/app/services/image_service.py:195-196`

Currently, if two parallel chunks upload the same file and both pass the application-level check, the second `db.flush()` will throw an unhandled `IntegrityError`. Fix:

```python
try:
    self.db.add(image)
    self.db.flush()
except IntegrityError:
    self.db.rollback()
    existing = self.db.query(Image).filter(
        Image.file_hash == file_hash, Image.user_id == self.user_id
    ).first()
    return None  # Treat as duplicate
```

**D3. Fix re-delivery guard to still count progress**

File: `backend/app/workers/tasks.py:374-379`

When a re-delivered image is skipped (status != PENDING), `_finish_ingest_job_item` is never called. This means the job hangs forever. Fix:

```python
if image.status != ImageStatus.PENDING:
    logger.info(f"Batch ingest: image {image_id} already {image.status.value}, skipping")
    _finish_ingest_job_item(db, job_id, failed=False)  # ← ADD THIS
    results.append({"image_id": image_id, "status": "skipped"})
    continue
```

### P1 — High (Reliability & Performance)

**D4. Move PIL metadata computation out of the HTTP request path**

File: `backend/app/services/image_service.py:171-174`

Currently `fast_ingest()` calls `compute_image_metadata()` (PIL open + phash) for every file inline. This is ~20-50ms per file, and blocks the async handler. Since `process_ingest_batch` already conditionally recomputes metadata (tasks.py:384-392), we can defer it entirely:

```python
# fast_ingest() — remove lines 171-174, simplify to:
mime_type = self.storage.get_mime_type(file_data)  # Still needed for save_image content-type

image = Image(
    ...
    mime_type=mime_type,
    width=None,    # Will be set by Celery task
    height=None,
    perceptual_hash=None,
    status=ImageStatus.PENDING,
)
```

This saves ~300-750ms per 15-file chunk.

**D5. Fix `folder.image_count` denormalization**

File: `backend/app/services/folder_service.py:155-160`

The count is computed as `COUNT(*) + added`, but the `COUNT(*)` doesn't include the just-added rows (they're in the same transaction but not yet flushed). Fix: compute after the commit, or better, compute it purely from the DB:

```python
if added:
    self.db.flush()  # Ensure FolderImage rows are visible
    folder.image_count = (
        self.db.query(func.count(FolderImage.id))
        .filter(FolderImage.folder_id == folder_id)
        .scalar() or 0
    )
    self.db.commit()
```

**D6. Add orphaned file cleanup mechanism**

There is no way to detect or clean up files that were written to storage but never had a DB record created. Options:
- **Reconciliation job**: Periodic Celery beat task that lists storage objects and compares against `images.object_key`. Delete orphans older than 1 hour.
- **Two-phase commit**: Write file, create DB record, on failure delete file. Simple try/finally in `fast_ingest()`.

### P2 — Medium (Developer Experience & Observability)

**D7. Consolidate folder assignment to a single code path**

Currently both `images.py:220-221` (API) and `tasks.py:238` (Celery) call `_assign_folder_on_completion()`. While idempotent, this is confusing and wastes resources (double cover composite generation). Consider: let only the Celery path do folder assignment. The API path can skip it — the Celery worker will catch it when the last image completes.

**D8. Add correlation IDs**

The `billing_context.py` already has `init_trace()` / `get_trace_id()` for billing. Extend this to upload:
- Frontend generates a `upload_session_id` (UUID) and sends it as a header
- Backend logs it alongside `job_id` in all upload-related log lines
- Celery tasks receive it as a parameter and set it in thread-local context
- All `write_log()` calls include it as `extra={"upload_session_id": ...}`

---

## E. Observability & Debuggability

### Current State

- **PipelineLog table**: Structured logs with category, level, duration, provider/model. Good foundation.
- **Job table**: Progress tracking with `progress / total_items`. Visible in Jobs page with 5s polling.
- **Logger calls**: Present in all critical paths but missing correlation across frontend→backend→worker.

### Recommended Instrumentation

| Where | What | How |
|-------|------|-----|
| Frontend | Upload session start/end timing | `console.time('upload-session')` + custom event |
| Frontend | Per-chunk timing & size | Log chunk index, file count, response time |
| API endpoint | Per-file ingest timing breakdown | `write_log()` with `extra={hash_ms, storage_ms, db_ms}` |
| API endpoint | Chunk summary: new/dup/failed counts | Already logged (images.py:223-227) |
| Celery task | Per-image processing breakdown | `write_log()` with `extra={read_ms, thumb_ms, commit_ms}` |
| Celery task | Thumbnail generation per-size timing | Instrument `generate_thumbnails()` |
| Job completion | Time from job create → complete | `job.completed_at - job.created_at` already available |
| Folder assignment | Success/failure, images assigned count | Already logged (tasks.py:179) |

### Metrics to Track

1. **Upload latency (P50/P95/P99)**: Time from first chunk sent to job completion
2. **Chunk processing time**: Time per `/upload/batch` request
3. **Ingest throughput**: Images/second through Celery worker
4. **Queue depth**: Redis list length for the default Celery queue
5. **Failure rate by stage**: `images WHERE status='failed'` / total, grouped by error_message pattern
6. **Orphan count**: Storage objects without matching DB records (needs reconciliation job)

---

## F. Concrete Code Hotspots

| File:Line | Function | Risk | Why |
|-----------|----------|------|-----|
| `api/images.py:186-193` | `upload_images_batch` — job.result update | **CRITICAL** | Race condition: concurrent chunks overwrite each other's `image_ids`. No locking. |
| `services/image_service.py:177` | `fast_ingest` — `save_image()` before DB | **HIGH** | Non-atomic: file orphaned if `db.flush()` fails. No cleanup. |
| `services/image_service.py:159-166` | `fast_ingest` — duplicate check | **HIGH** | Application-level check + DB constraint, but `IntegrityError` unhandled → 500 error + orphaned file. |
| `workers/tasks.py:374-379` | `process_ingest_batch` — re-delivery guard | **HIGH** | Skipped images don't call `_finish_ingest_job_item()` → job hangs forever. |
| `services/image_service.py:171-174` | `fast_ingest` — `compute_image_metadata()` | **MEDIUM** | PIL + phash inline in HTTP handler. ~20-50ms/file adds up with 15 files/chunk. |
| `services/folder_service.py:155-160` | `add_images_to_folder` — image_count | **MEDIUM** | Denormalized count computed without locking → drift under concurrency. |
| `workers/tasks.py:405+407` | `process_ingest_batch` — commit then finish_job | **MEDIUM** | Task crash between `db.commit()` and `_finish_ingest_job_item()` → image processed but progress not counted. |
| `api/images.py:140` | `upload_images_batch` — `file.read()` | **LOW** | Entire file in memory. 15 large files = 150MB+ per chunk. 3 parallel chunks = 450MB+. |
| `workers/celery_app.py:86` | Docker compose: `--concurrency=1` | **LOW** | Only 1 concurrent task on default worker. Ingestion bottleneck for large uploads. |

---

## G. Proposed Minimal Patch Set (80/20)

These 4 changes address the most impactful bugs with minimal code changes:

### Patch 1: Lock `job.result` updates (CRITICAL — fixes folder assignment)

```python
# api/images.py:179-180 — change from:
job = db.query(Job).filter(Job.id == job.id).first()
# to:
job = db.query(Job).with_for_update().filter(Job.id == job.id).first()
```

**1 line changed. Fixes the race condition where concurrent chunk uploads overwrite each other's image ID lists.**

### Patch 2: Fix re-delivery guard to count progress (HIGH — fixes hanging jobs)

```python
# workers/tasks.py:374-379 — add _finish_ingest_job_item call:
if image.status != ImageStatus.PENDING:
    logger.info(f"Batch ingest: image {image_id} already {image.status.value}, skipping")
    _finish_ingest_job_item(db, job_id, failed=False)  # ← ADD
    results.append({"image_id": image_id, "status": "skipped"})
    continue
```

**1 line added. Prevents jobs from hanging forever after worker restart/redelivery.**

### Patch 3: Handle `IntegrityError` in `fast_ingest()` (HIGH — prevents 500 errors)

```python
# services/image_service.py:195-196 — wrap flush in try/except:
from sqlalchemy.exc import IntegrityError

try:
    self.db.add(image)
    self.db.flush()
except IntegrityError:
    self.db.rollback()
    return None  # Treat as duplicate
```

**5 lines added. Gracefully handles concurrent duplicate uploads instead of 500 errors.**

### Patch 4: Remove inline PIL from `fast_ingest()` (MEDIUM — speeds up uploads)

```python
# services/image_service.py:171-174 — replace compute_image_metadata with just MIME detection:
mime_type = self.storage.get_mime_type(file_data)

image = Image(
    ...
    mime_type=mime_type,
    width=None,       # Celery task will compute
    height=None,      # Celery task will compute
    perceptual_hash=None,  # Celery task will compute
    ...
)
```

The Celery task already has the fallback path (`tasks.py:384-392`: `if image.width is None`). This change removes ~20-50ms per file from the HTTP handler, cutting chunk response time by ~300-750ms.

---

## Next Actions Checklist

1. [ ] **Apply Patch 1** — `with_for_update()` on job.result reads in `api/images.py`
2. [ ] **Apply Patch 2** — Add `_finish_ingest_job_item()` to re-delivery skip path in `tasks.py`
3. [ ] **Apply Patch 3** — Catch `IntegrityError` in `fast_ingest()`
4. [ ] **Apply Patch 4** — Remove `compute_image_metadata()` from `fast_ingest()`, rely on Celery fallback
5. [ ] **Verify**: Upload 100 images to a new folder with 3 parallel chunks → confirm all images appear in folder
6. [ ] **Verify**: Kill Celery worker mid-batch, restart → confirm job completes (no hung progress)
7. [ ] **Verify**: Upload same file in two simultaneous chunks → confirm no 500 error, both resolve as duplicate
8. [ ] **Fix `image_count` denormalization** — flush before counting in `folder_service.py:155-160`
9. [ ] **Add orphan cleanup** — Celery beat task comparing storage objects to DB records
10. [ ] **Consider**: Increase default worker concurrency to 2 (`docker-compose.yml:86`) for faster thumbnail throughput
11. [ ] **Consider**: Add upload session correlation IDs for end-to-end debugging
