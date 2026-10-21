"""Studio generation jobs — Postgres queue + optional inline threads (dev)."""

from __future__ import annotations

import datetime
import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from xai_keys import key_for_slot, max_concurrent_jobs, next_key, reset_key, use_key

PREFIX = "studio-gen"
MAX_CONCURRENT = max_concurrent_jobs()


def _queue_backend() -> str:
    return (os.getenv("STUDIO_QUEUE_BACKEND") or "postgres").strip().lower()


def _inline_workers() -> bool:
    raw = (os.getenv("STUDIO_INLINE_WORKERS") or "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    # Default: inline only when using legacy storage queue (local dev).
    return _queue_backend() == "storage"


class StudioJobRunner:
    def __init__(self, supabase, flask_app):
        self.supabase = supabase
        self.app = flask_app
        self.max_slots = MAX_CONCURRENT
        self._slot_sem = threading.BoundedSemaphore(max(1, self.max_slots))
        self._active = 0
        self._waiting = 0
        self._stats_lock = threading.Lock()
        self._postgres_ok: Optional[bool] = None
        self._postgres_failed_at = 0.0
        self._on_finish: List[Callable] = []
        # Wire PoYo CDN GLB proxy early (Render has no *.glb on disk — gitignored).
        try:
            import poyo_cdn_proxy
            poyo_cdn_proxy.init_app(flask_app)
        except Exception:
            pass
        try:
            import discord_bridge
            discord_bridge.attach_runner(self)
        except Exception:
            pass

    def _use_postgres(self) -> bool:
        if _queue_backend() != "postgres":
            return False
        if self._postgres_ok is False:
            # One failed probe used to pin this process to the storage queue until
            # restart; retry the table every 5 minutes instead.
            if time.time() - self._postgres_failed_at < 300:
                return False
            self._postgres_ok = None
        if self._postgres_ok is True:
            return True
        try:
            self.supabase.table("generation_jobs").select("id").limit(1).execute()
            self._postgres_ok = True
            return True
        except Exception:
            self.app.logger.warning(
                "generation_jobs table missing — run migrations/20260710_generation_jobs.sql; "
                "falling back to storage queue"
            )
            self._postgres_ok = False
            self._postgres_failed_at = time.time()
            return False

    def _stats(self) -> Dict[str, int]:
        stats = {"active": 0, "waiting": 0, "max_concurrent": self.max_slots}
        if self._use_postgres():
            try:
                pending = self.supabase.table("generation_jobs").select("id", count="exact").eq(
                    "status", "pending"
                ).execute()
                processing = self.supabase.table("generation_jobs").select("id", count="exact").eq(
                    "status", "processing"
                ).execute()
                stats["waiting"] = int(getattr(pending, "count", None) or 0)
                stats["active"] = int(getattr(processing, "count", None) or 0)
                return stats
            except Exception:
                pass
        with self._stats_lock:
            stats["active"] = self._active
            stats["waiting"] = self._waiting
        return stats

    # --- storage backend (legacy / local dev) ---

    def _path(self, job_id: str, suffix: Optional[str] = None) -> str:
        if suffix:
            return f"{PREFIX}/{job_id}.{suffix}.json"
        return f"{PREFIX}/{job_id}.json"

    def _upload(self, path: str, data: dict) -> None:
        """Write job marker JSON. Must UPSERT — re-upload of processing.json is how live progress updates.
        Plain upload fails when the file already exists → bar stuck at 55% forever."""
        raw = json.dumps(data).encode("utf-8")
        bucket = self.supabase.storage.from_("originals")
        opts = {"content-type": "application/json", "upsert": "true"}
        try:
            bucket.upload(path, raw, file_options=opts)
            return
        except Exception:
            pass
        # Older clients / API quirks: remove then write
        try:
            bucket.remove([path])
        except Exception:
            pass
        try:
            bucket.upload(
                path,
                raw,
                file_options={"content-type": "application/json", "upsert": "true"},
            )
        except Exception:
            bucket.upload(path, raw, file_options={"content-type": "application/json"})

    def _download_json(self, path: str) -> Optional[dict]:
        try:
            raw = self.supabase.storage.from_("originals").download(path)
            if isinstance(raw, memoryview):
                raw = raw.tobytes()
            if isinstance(raw, (bytes, bytearray)):
                text = raw.decode("utf-8")
            else:
                text = str(raw)
            return json.loads(text)
        except Exception:
            return None

    def _create_storage(self, user_id: int, kind: str, payload: dict) -> str:
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "user_id": user_id,
            "kind": kind,
            "payload": payload,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }
        self._upload(self._path(job_id), job)
        return job_id

    def _status_storage(self, job_id: str, user_id: int) -> Dict[str, Any]:
        job = self._download_json(self._path(job_id))
        if not job or int(job.get("user_id") or 0) != int(user_id):
            return {"error": "Job not found."}

        stats = self._stats()
        base = {"job_id": job_id, "kind": job.get("kind"), "queue": stats}

        if self._download_json(self._path(job_id, "failed")):
            failed = self._download_json(self._path(job_id, "failed")) or {}
            return {**base, "status": "failed", "error": failed.get("error") or "Generation failed."}
        if self._download_json(self._path(job_id, "done")):
            done = self._download_json(self._path(job_id, "done")) or {}
            return {**base, "status": "done", **done}
        if self._download_json(self._path(job_id, "processing")):
            processing = self._download_json(self._path(job_id, "processing")) or {}
            out = {**base, "status": "processing"}
            # Live xAI progress written by poll (honest bar — not a timer)
            if processing.get("progress") is not None:
                try:
                    out["progress"] = int(processing.get("progress"))
                except (TypeError, ValueError):
                    pass
            if processing.get("message"):
                out["message"] = processing.get("message")
            return out
        if self._download_json(self._path(job_id, "queued")):
            queued = self._download_json(self._path(job_id, "queued")) or {}
            return {**base, "status": "queued", "queue_ahead": queued.get("queue_ahead", 0)}
        return {**base, "status": "pending"}

    # --- postgres backend ---

    def _create_postgres(self, user_id: int, kind: str, payload: dict) -> str:
        # Double-click guard: one click must mean one generation. If this user
        # already has a live job of the same kind created <60s ago, hand back THAT
        # job id instead of enqueueing a duplicate (live incident 2026-07-16: two
        # arena videos fired 13s apart from one button). All click paths converge
        # on the same job, so the UI still gets a job to poll.
        try:
            cutoff = (
                datetime.datetime.utcnow() - datetime.timedelta(seconds=60)
            ).isoformat()
            dup = (
                self.supabase.table("generation_jobs")
                .select("id")
                .eq("user_id", user_id)
                .eq("kind", kind)
                .in_("status", ["pending", "processing"])
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if dup.data:
                existing = str(dup.data[0].get("id") or "")
                if existing:
                    self.app.logger.info(
                        "dedupe: user %s re-clicked %s within 60s → reusing job %s",
                        user_id, kind, existing,
                    )
                    return existing
        except Exception:
            pass  # dedupe is best-effort — never block a legit generation
        row = self.supabase.table("generation_jobs").insert({
            "user_id": user_id,
            "kind": kind,
            "payload": payload,
            "status": "pending",
        }).execute()
        data = (row.data or [{}])[0]
        job_id = str(data.get("id") or "")
        if not job_id:
            raise RuntimeError("Failed to enqueue generation job.")
        return job_id

    def _queue_ahead_postgres(self, job_id: str) -> int:
        try:
            res = self.supabase.rpc("studio_queue_ahead", {"p_job_id": job_id}).execute()
            if res.data is not None:
                return int(res.data)
        except Exception:
            pass
        try:
            job = self.supabase.table("generation_jobs").select("created_at").eq("id", job_id).single().execute()
            created = (job.data or {}).get("created_at")
            if not created:
                return 0
            pending = self.supabase.table("generation_jobs").select("id", count="exact").eq(
                "status", "pending"
            ).lt("created_at", created).execute()
            return int(getattr(pending, "count", None) or 0)
        except Exception:
            return 0

    def _status_postgres(self, job_id: str, user_id: int) -> Dict[str, Any]:
        try:
            res = self.supabase.table("generation_jobs").select("*").eq("id", job_id).single().execute()
        except Exception:
            return {"error": "Job not found."}
        job = res.data or {}
        if int(job.get("user_id") or 0) != int(user_id):
            return {"error": "Job not found."}

        stats = self._stats()
        base = {
            "job_id": job_id,
            "kind": job.get("kind"),
            "queue": stats,
        }
        status = job.get("status") or "pending"
        if status == "done":
            result = job.get("result") or {}
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except Exception:
                    result = {}
            return {**base, "status": "done", **result}
        if status == "failed":
            return {**base, "status": "failed", "error": job.get("error") or "Generation failed."}
        if status == "processing":
            # Stale-job reaper: a worker claimed this job but died/hung — without
            # this, the row stays "processing" forever and the user's spinner never
            # ends (live incident 2026-07-16: arena jobs stuck 12h+). Video poll
            # worst-case is 8 min, so 15 min of processing = the job is lost.
            started = job.get("started_at") or job.get("created_at")
            try:
                t0 = datetime.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                age = (datetime.datetime.now(datetime.timezone.utc) - t0).total_seconds()
            except Exception:
                age = 0
            if age > 15 * 60:
                msg = ("The worker lost this job (server restart or crash mid-render). "
                       "You were NOT charged — please retry.")
                try:
                    self._finish_postgres(job_id, error=msg)
                except Exception:
                    pass
                return {**base, "status": "failed", "error": msg}
            out = {**base, "status": "processing"}
            # Live progress parked on result while still processing (see inline worker)
            result = job.get("result") or {}
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except Exception:
                    result = {}
            if isinstance(result, dict) and result.get("progress") is not None:
                try:
                    out["progress"] = int(result.get("progress"))
                except (TypeError, ValueError):
                    pass
                if result.get("phase"):
                    out["message"] = result.get("phase")
            return out
        if status == "pending":
            ahead = self._queue_ahead_postgres(job_id)
            st = "queued" if ahead > 0 else "pending"
            return {**base, "status": st, "queue_ahead": ahead}
        return {**base, "status": status}

    def _finish_postgres(self, job_id: str, *, result: Optional[dict] = None, error: Optional[str] = None) -> None:
        patch = {"finished_at": datetime.datetime.utcnow().isoformat()}
        if error:
            patch.update({"status": "failed", "error": error[:500]})
        else:
            patch.update({"status": "done", "result": result or {}})
        self.supabase.table("generation_jobs").update(patch).eq("id", job_id).execute()
        self._emit_finish(job_id, result=result, error=error)

    def on_finish(self, fn: Callable) -> None:
        """Register a callback after a job reaches done/failed. Must not raise."""
        if fn not in self._on_finish:
            self._on_finish.append(fn)

    def _emit_finish(
        self,
        job_id: str,
        *,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        hooks = list(getattr(self, "_on_finish", None) or [])
        if not hooks:
            return
        job: Optional[dict] = None
        try:
            job = self.load(job_id)
        except Exception:
            job = None
        user_id = 0
        kind = ""
        payload: Any = {}
        if isinstance(job, dict):
            try:
                user_id = int(job.get("user_id") or 0)
            except Exception:
                user_id = 0
            kind = str(job.get("kind") or "")
            payload = job.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
        for fn in hooks:
            try:
                fn(
                    job_id=job_id,
                    user_id=user_id,
                    kind=kind,
                    payload=payload if isinstance(payload, dict) else {},
                    result=result if isinstance(result, dict) else {},
                    error=error,
                )
            except Exception:
                try:
                    self.app.logger.exception("studio job finish hook failed")
                except Exception:
                    pass

    # --- public API ---

    def create(self, user_id: int, kind: str, payload: dict) -> str:
        if self._use_postgres():
            return self._create_postgres(user_id, kind, payload)
        return self._create_storage(user_id, kind, payload)

    def load(self, job_id: str) -> Optional[dict]:
        if self._use_postgres():
            try:
                res = self.supabase.table("generation_jobs").select("*").eq("id", job_id).single().execute()
                return res.data
            except Exception:
                return None
        return self._download_json(self._path(job_id))

    def mark(self, job_id: str, suffix: str, data: dict) -> None:
        if self._use_postgres():
            return
        self._upload(self._path(job_id, suffix), data)

    def marker_exists(self, job_id: str, suffix: str) -> bool:
        if self._use_postgres():
            return False
        return self._download_json(self._path(job_id, suffix)) is not None

    def status(self, job_id: str, user_id: int) -> Dict[str, Any]:
        if self._use_postgres():
            out = self._status_postgres(job_id, user_id)
            if "status" not in out:
                # Another process may have queued it on the storage fallback.
                alt = self._status_storage(job_id, user_id)
                if "status" in alt:
                    return alt
            return out
        return self._status_storage(job_id, user_id)

    def start(self, job_id: str, worker: Callable[[], dict]) -> None:
        # External worker fleet owns postgres jobs only when inline is explicitly off
        # AND the generation_jobs table is live. Otherwise process here (inline slot pool).
        if self._use_postgres() and not _inline_workers():
            return
        self._start_inline(job_id, worker)

    def _start_inline(self, job_id: str, worker: Callable[[], dict]) -> None:
        app = self.app
        use_pg = self._use_postgres()

        def _run() -> None:
            acquired = False
            key_token = None
            with app.app_context():
                try:
                    with self._stats_lock:
                        self._waiting += 1
                        ahead = max(0, self._active + self._waiting - 1 - self.max_slots)
                    if use_pg:
                        try:
                            self.supabase.table("generation_jobs").update({
                                "status": "pending",
                            }).eq("id", job_id).eq("status", "pending").execute()
                        except Exception:
                            pass
                    else:
                        self.mark(job_id, "queued", {
                            "queued_at": datetime.datetime.utcnow().isoformat(),
                            "queue_ahead": ahead,
                        })

                    self._slot_sem.acquire()
                    acquired = True
                    with self._stats_lock:
                        self._waiting -= 1
                        self._active += 1
                        slot = self._active - 1
                    # Round-robin across ALL keys (not always keys[0] for sequential gens)
                    key_token = use_key(next_key())
                    if use_pg:
                        try:
                            self.supabase.table("generation_jobs").update({
                                "status": "processing",
                                "started_at": datetime.datetime.utcnow().isoformat(),
                                "key_slot": slot,
                            }).eq("id", job_id).execute()
                        except Exception:
                            pass
                    else:
                        self.mark(job_id, "processing", {
                            "started_at": datetime.datetime.utcnow().isoformat(),
                        })
                    # Live xAI progress → job status so the Videos bar can move for real
                    progress_token = None
                    try:
                        import app as app_module
                        started_at = datetime.datetime.utcnow().isoformat()

                        def _on_video_progress(pct, status_label=""):
                            p = max(0, min(100, int(pct or 0)))
                            # Map xAI 0–100 into processing band 15–92 so stages stay honest
                            mapped = 15 if p < 1 else min(92, 15 + int(p * 0.77))
                            if use_pg:
                                try:
                                    self.supabase.table("generation_jobs").update({
                                        "result": {
                                            "progress": mapped,
                                            "xai_progress": p,
                                            "phase": status_label or "processing",
                                        },
                                    }).eq("id", job_id).eq("status", "processing").execute()
                                except Exception:
                                    pass
                            else:
                                self.mark(job_id, "processing", {
                                    "started_at": started_at,
                                    "progress": mapped,
                                    "xai_progress": p,
                                    "message": status_label or "Rendering…",
                                })

                        if getattr(app_module, "_video_job_progress_cb", None) is not None:
                            progress_token = app_module._video_job_progress_cb.set(_on_video_progress)
                    except Exception:
                        progress_token = None
                    try:
                        result = worker()
                    finally:
                        try:
                            import app as app_module
                            if progress_token is not None and getattr(app_module, "_video_job_progress_cb", None) is not None:
                                app_module._video_job_progress_cb.reset(progress_token)
                        except Exception:
                            pass
                    done_result = result if isinstance(result, dict) else {"result": result}
                    if use_pg:
                        self._finish_postgres(job_id, result=done_result)
                    else:
                        self.mark(job_id, "done", done_result)
                        self._emit_finish(job_id, result=done_result)
                except Exception as exc:
                    app.logger.exception("studio job %s failed", job_id)
                    # Prefer the real exception text (moderation / poll 400 body) — never hide it
                    err_txt = str(exc)[:500] if str(exc) else "Generation failed."
                    if use_pg:
                        self._finish_postgres(job_id, error=err_txt)
                    else:
                        self.mark(job_id, "failed", {"error": err_txt})
                        self._emit_finish(job_id, error=err_txt)
                finally:
                    if key_token is not None:
                        reset_key(key_token)
                    if acquired:
                        with self._stats_lock:
                            self._active = max(0, self._active - 1)
                        self._slot_sem.release()
                    else:
                        with self._stats_lock:
                            self._waiting = max(0, self._waiting - 1)

        threading.Thread(target=_run, name=f"studio-job-{job_id[:8]}", daemon=True).start()

    def _dispatch(self, kind: str, user_id: int, payload: dict) -> dict:
        from studio_task_handlers import dispatch
        return dispatch(kind, user_id, payload)

    def _process_claimed(self, job: dict, worker_id: str, slot: int) -> None:
        job_id = str(job.get("id") or "")
        user_id = int(job.get("user_id") or 0)
        kind = job.get("kind") or ""
        payload = job.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}

        key_token = None
        with self.app.app_context():
            try:
                key_token = use_key(next_key())
                try:
                    self.supabase.table("generation_jobs").update({"key_slot": slot}).eq("id", job_id).execute()
                except Exception:
                    pass
                result = self._dispatch(kind, user_id, payload)
                self._finish_postgres(job_id, result=result)
            except Exception as exc:
                import app as app_module
                pending_cls = getattr(app_module, "XaiVideoPending", None)
                if pending_cls is not None and isinstance(exc, pending_cls):
                    # Video still rendering on xAI — record it so the Library
                    # reclaim sweep delivers it once xAI finishes (never charged yet,
                    # so the cost rides along and is billed at reclaim time).
                    try:
                        app_module._record_pending_video(
                            user_id,
                            (payload or {}).get("prompt") or "",
                            exc.job_id,
                            exc.key,
                            cost=0 if payload.get("is_admin") else int(payload.get("cost") or 0),
                        )
                        self.app.logger.info(
                            "worker %s job %s → video_pending (xai job %s)",
                            worker_id, job_id, exc.job_id,
                        )
                    except Exception:
                        self.app.logger.exception("recording pending video failed for job %s", job_id)
                    self._finish_postgres(
                        job_id,
                        error="Your video is taking longer than usual — it's still rendering "
                              "and will appear in your 📚 Library automatically once ready.",
                    )
                else:
                    self.app.logger.exception("worker %s job %s failed", worker_id, job_id)
                    self._finish_postgres(job_id, error=str(exc))
            finally:
                if key_token is not None:
                    reset_key(key_token)

    def _claim_postgres(self, worker_id: str) -> Optional[dict]:
        try:
            res = self.supabase.rpc("claim_studio_job", {"p_worker_id": worker_id}).execute()
            data = res.data
            if not data:
                return None
            if isinstance(data, list):
                return data[0] if data else None
            return data
        except Exception as exc:
            self.app.logger.warning("claim_studio_job failed: %s", exc)
            return None

    def _worker_loop(self, worker_id: str, slot: int) -> None:
        idle_sleep = float(os.getenv("STUDIO_WORKER_IDLE_SEC", "0.5"))
        while True:
            job = self._claim_postgres(worker_id)
            if not job:
                time.sleep(idle_sleep)
                continue
            self._process_claimed(job, worker_id, slot)

    def run_worker_pool(self, worker_id: str) -> None:
        if not self._use_postgres():
            raise RuntimeError("Worker requires STUDIO_QUEUE_BACKEND=postgres and generation_jobs table.")

        threads: List[threading.Thread] = []
        for slot in range(self.max_slots):
            t = threading.Thread(
                target=self._worker_loop,
                args=(worker_id, slot),
                name=f"studio-worker-{slot}",
                daemon=True,
            )
            t.start()
            threads.append(t)

        while True:
            time.sleep(60)
