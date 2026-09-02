"""Tests for background scheduler and worker."""

import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from invoiceledger.storage import Storage
from invoiceledger.intake import IntakeManager
from invoiceledger.scheduler import IntakeWorker


def test_scheduler_run_once(tmp_path):
    storage = Storage(str(tmp_path / "test_sched.db"))
    intake = IntakeManager(storage)
    
    mock_callback = MagicMock()
    worker = IntakeWorker(
        intake_manager=intake,
        interval_seconds=10,
        watch_dirs=[tmp_path / "hot_folder"],
        on_cycle_complete=mock_callback,
    )

    result = worker.run_once()
    assert "total_processed" in result
    assert worker.total_cycles == 1
    assert mock_callback.called


def test_scheduler_start_stop(tmp_path):
    storage = Storage(str(tmp_path / "test_sched2.db"))
    intake = IntakeManager(storage)
    
    worker = IntakeWorker(
        intake_manager=intake,
        interval_seconds=1,
        watch_dirs=[tmp_path / "hot_folder"],
    )

    assert not worker.is_running
    worker.start()
    assert worker.is_running
    time.sleep(0.1)
    worker.stop()
    assert not worker.is_running


def test_process_lock_concurrency(tmp_path):
    """Verifies that ProcessLock prevents two concurrent workers from running simultaneously."""
    from invoiceledger.scheduler import ProcessLock
    lock_file = tmp_path / "test.lock"

    lock1 = ProcessLock(str(lock_file))
    lock2 = ProcessLock(str(lock_file))

    assert lock1.acquire() is True
    assert lock2.acquire() is False

    lock1.release()
    assert lock2.acquire() is True
    lock2.release()


def test_scheduler_does_not_start_in_multiple_workers(tmp_path):
    """Verifies that scheduler advisory lock prevents starting more than one worker process simultaneously."""
    storage = Storage(str(tmp_path / "test_multi.db"))
    intake = IntakeManager(storage)
    shared_lock_file = str(tmp_path / "shared_intake.lock")

    worker1 = IntakeWorker(
        intake_manager=intake,
        interval_seconds=10,
        lock_file=shared_lock_file,
    )
    worker2 = IntakeWorker(
        intake_manager=intake,
        interval_seconds=10,
        lock_file=shared_lock_file,
    )

    # First worker starts successfully
    started1 = worker1.start()
    assert started1 is True
    assert worker1.is_running is True

    # Second worker attempts to start but is blocked by the advisory lock
    started2 = worker2.start()
    assert started2 is False
    assert worker2.is_running is False

    # Stop worker 1, freeing the advisory lock
    worker1.stop()
    assert worker1.is_running is False

    # Now worker 2 can start successfully
    started2_after = worker2.start()
    assert started2_after is True
    assert worker2.is_running is True

    worker2.stop()
    assert worker2.is_running is False


def test_scheduler_web_concurrency_guard(tmp_path, monkeypatch):
    """Verifies that WEB_CONCURRENCY > 1 prevents starting scheduler in secondary workers."""
    storage = Storage(str(tmp_path / "test_guard.db"))
    intake = IntakeManager(storage)

    # Set multi-worker environment
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("WORKER_ID", "2")

    worker_secondary = IntakeWorker(
        intake_manager=intake,
        interval_seconds=10,
        lock_file=str(tmp_path / "guard_test.lock"),
    )

    started = worker_secondary.start()
    assert started is False
    assert worker_secondary.is_running is False

    # Primary worker (WORKER_ID=1) can start
    monkeypatch.setenv("WORKER_ID", "1")
    worker_primary = IntakeWorker(
        intake_manager=intake,
        interval_seconds=10,
        lock_file=str(tmp_path / "guard_test.lock"),
    )
    started_primary = worker_primary.start()
    assert started_primary is True
    assert worker_primary.is_running is True
    worker_primary.stop()
