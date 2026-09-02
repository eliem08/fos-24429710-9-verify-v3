"""Background Worker & Scheduled Trigger Engine for Automated Invoice Intake."""

import os
import sys
import time
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime, timezone

from .intake import IntakeManager
from .models import EmailSourceConfig, PortalSourceConfig

logger = logging.getLogger("invoiceledger.scheduler")


class ProcessLock:
    """Cross-platform advisory file lock to prevent duplicate runs across multi-worker deployments."""

    def __init__(self, lock_file: str = "intake_worker.lock"):
        self.lock_path = Path(lock_file)
        self._fd = None

    def acquire(self) -> bool:
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = open(self.lock_path, "a+")
            if sys.platform == "win32":
                import msvcrt
                try:
                    self._fd.seek(0)
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                    return True
                except (IOError, OSError):
                    try:
                        self._fd.close()
                    except Exception:
                        pass
                    self._fd = None
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except (IOError, OSError):
                    try:
                        self._fd.close()
                    except Exception:
                        pass
                    self._fd = None
                    return False
        except Exception:
            return False

    def release(self):
        if self._fd:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fd.seek(0)
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._fd.close()
            except Exception:
                pass
            self._fd = None


class IntakeWorker:
    """Recurring background worker that automatically polls emails, vendor portals,
    and hot folders on a scheduled interval without requiring human manual triggers.
    Includes cross-process locking to support multi-worker server deployments safely.
    """

    def __init__(
        self,
        intake_manager: IntakeManager,
        interval_seconds: int = 60,
        watch_dirs: Optional[List[Path]] = None,
        email_config: Optional[EmailSourceConfig] = None,
        portal_configs: Optional[List[PortalSourceConfig]] = None,
        auto_commit_if_confident: bool = True,
        on_cycle_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        lock_file: str = "intake_worker.lock",
    ):
        self.intake = intake_manager
        self.interval_seconds = max(5, interval_seconds)
        self.watch_dirs = watch_dirs or [Path("hot_folder"), Path("uploads")]
        self.email_config = email_config
        self.portal_configs = portal_configs or []
        self.auto_commit_if_confident = auto_commit_if_confident
        self.on_cycle_complete = on_cycle_complete
        self.lock_file = lock_file

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._scheduler_lock: Optional[ProcessLock] = None
        self.last_run_time: Optional[str] = None
        self.total_cycles: int = 0
        self.total_invoices_ingested: int = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _execute_sync(self) -> Dict[str, Any]:
        """Internal helper to execute the intake cycle and record metrics."""
        result = self.intake.poll_and_ingest(
            watch_dirs=self.watch_dirs,
            email_config=self.email_config,
            portal_configs=self.portal_configs,
            auto_commit_if_confident=self.auto_commit_if_confident,
        )
        self.last_run_time = datetime.now(timezone.utc).isoformat()
        self.total_cycles += 1
        self.total_invoices_ingested += result.get("total_processed", 0)

        if self.on_cycle_complete:
            try:
                self.on_cycle_complete(result)
            except Exception:
                pass

        return result

    def run_once(self) -> Dict[str, Any]:
        """Executes a single end-to-end sync cycle if process lock is acquired."""
        if self._scheduler_lock is not None:
            return self._execute_sync()

        lock = ProcessLock(self.lock_file)
        if not lock.acquire():
            logger.debug("Another worker process is currently holding the intake lock; skipping cycle.")
            return {
                "total_processed": 0,
                "committed_count": 0,
                "pending_count": 0,
                "duplicate_count": 0,
                "invoices": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "skipped_due_to_lock": True,
            }

        try:
            return self._execute_sync()
        finally:
            lock.release()

    def start(self) -> bool:
        """Starts the background worker thread if not already running and guard/lock condition permits."""
        if self._is_running:
            return True

        # Multi-worker concurrency guard
        web_concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
        if web_concurrency.isdigit() and int(web_concurrency) > 1:
            worker_id = os.environ.get("WORKER_ID", os.environ.get("UVICORN_WORKER_ID", "1")).strip()
            if worker_id not in ("1", "primary"):
                logger.info(
                    "Multi-worker guard: WEB_CONCURRENCY=%s but current process is worker %s. "
                    "Skipping intake scheduler start in secondary worker.",
                    web_concurrency,
                    worker_id,
                )
                return False

        # Acquire process advisory lock for the scheduler lifetime
        lock = ProcessLock(self.lock_file)
        if not lock.acquire():
            logger.info("Advisory lock held by another process. Skipping intake scheduler start.")
            return False

        self._scheduler_lock = lock
        self._stop_event.clear()
        self._is_running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="InvoiceLedger-Worker")
        self._thread.start()
        logger.info(f"Background intake worker started with interval: {self.interval_seconds}s")
        return True

    def stop(self):
        """Stops the background worker thread and releases advisory lock."""
        if not self._is_running:
            if self._scheduler_lock:
                self._scheduler_lock.release()
                self._scheduler_lock = None
            return

        self._stop_event.set()
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

        if self._scheduler_lock:
            self._scheduler_lock.release()
            self._scheduler_lock = None

        logger.info("Background intake worker stopped.")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                self._execute_sync()
            except Exception as e:
                logger.error(f"Error during scheduled intake cycle: {e}")

            # Sleep in small increments for responsive stop
            for _ in range(int(self.interval_seconds)):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self._is_running,
            "interval_seconds": self.interval_seconds,
            "last_run_time": self.last_run_time,
            "total_cycles": self.total_cycles,
            "total_invoices_ingested": self.total_invoices_ingested,
            "watch_dirs": [str(d) for d in self.watch_dirs],
        }
