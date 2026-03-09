"""
Lightweight cross-process activity event writer for RAAF.

Appends newline-delimited JSON events to data/activity_events.jsonl.
Designed for zero-overhead import — only stdlib (json, time, pathlib).

Usage in CLI scripts:
    from utils.activity_writer import worker_start, worker_complete, token_use

Events are consumed by web/activity_monitor.py and streamed to the Admin UI.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

_EVENTS_FILE = Path(__file__).parent.parent.parent / "data" / "activity_events.jsonl"
_lock = threading.Lock()

# Thread-local storage so claude_client.py can pick up the current worker_id
_thread_local = threading.local()


def _write(event: dict) -> None:
    event.setdefault("ts", time.time())
    event.setdefault("pid", os.getpid())
    line = json.dumps(event, default=str) + "\n"
    try:
        with _lock:
            with open(_EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def worker_start(worker_id: str, candidate: str, req_id: str, client: str = "") -> None:
    """Register a new assessment worker."""
    _write({
        "type": "worker_start",
        "worker_id": worker_id,
        "candidate": candidate,
        "req_id": req_id,
        "client": client,
    })


def worker_stage(worker_id: str, stage: str) -> None:
    """Update the stage of an active worker.

    Stages: queued → screening → assessing → saving
    """
    _write({"type": "worker_stage", "worker_id": worker_id, "stage": stage})


def worker_complete(
    worker_id: str,
    score: float | None = None,
    recommendation: str = "",
    candidate: str = "",
    error: str = "",
) -> None:
    """Mark a worker as completed (successfully or with error)."""
    _write({
        "type": "worker_complete",
        "worker_id": worker_id,
        "score": score,
        "recommendation": recommendation,
        "candidate": candidate,
        "error": error,
    })


def token_use(model: str, input_tokens: int, output_tokens: int, worker_id: str = "") -> None:
    """Record token consumption from a Claude API call."""
    _write({
        "type": "token_use",
        "model": model,
        "input": input_tokens,
        "output": output_tokens,
        "worker_id": worker_id,
    })


def make_worker_id() -> str:
    """Generate a unique worker ID (PID + thread + timestamp)."""
    return f"{os.getpid()}-{threading.get_ident()}-{int(time.time() * 1000) % 100000}"
