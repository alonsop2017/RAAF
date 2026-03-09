"""
RAAF Activity Monitor — reads the JSONL events file and produces live snapshots.

CLI scripts write events via scripts/utils/activity_writer.py.
The SSE endpoint at /admin/activity/stream calls get_snapshot() every second.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

_EVENTS_FILE = Path(__file__).parent.parent / "data" / "activity_events.jsonl"

# Pricing per million tokens (blended Anthropic pricing, 2025)
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001":    {"input": 0.80,  "output": 4.00},
    "claude-haiku-4-5":             {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":            {"input": 3.00,  "output": 15.00},
    "claude-sonnet-4-20250514":     {"input": 3.00,  "output": 15.00},
    "claude-opus-4-6":              {"input": 15.00, "output": 75.00},
}
_DEFAULT_PRICE = {"input": 3.00, "output": 15.00}


def _price(model: str, inp: int, out: int) -> float:
    p = _PRICING.get(model, _DEFAULT_PRICE)
    return (inp * p["input"] + out * p["output"]) / 1_000_000


def get_snapshot(active_window_s: int = 600, session_window_s: int = 86400) -> dict:
    """
    Read the JSONL events file and return a JSON-serialisable snapshot.

    Args:
        active_window_s: Seconds to look back for active workers (default 10 min).
        session_window_s: Seconds to look back for session token totals (default 24 h).

    Returns dict with keys:
        workers          — list of active worker dicts
        session_tokens   — {input, output, calls, cost_usd}
        recent           — list of last 15 completed assessments
        throughput_buckets — 6-element list (10s slices, oldest→newest, last 60s)
        ts               — current epoch timestamp
    """
    now = time.time()
    active_cutoff  = now - active_window_s
    session_cutoff = now - session_window_s

    # Read the last 10 000 lines to bound memory
    try:
        raw = _EVENTS_FILE.read_text(encoding="utf-8")
        lines = raw.strip().splitlines()[-10_000:]
    except Exception:
        lines = []

    workers: dict[str, dict] = {}
    session_tokens = {"input": 0, "output": 0, "calls": 0, "cost_usd": 0.0}
    recent: list[dict] = []
    completion_times: list[float] = []

    for line in lines:
        try:
            e = json.loads(line)
        except Exception:
            continue

        ts    = float(e.get("ts", 0))
        etype = e.get("type", "")

        # ── Token accounting (session window) ─────────────────────────────
        if etype == "token_use" and ts > session_cutoff:
            inp   = int(e.get("input", 0))
            out   = int(e.get("output", 0))
            model = e.get("model", "")
            session_tokens["input"]    += inp
            session_tokens["output"]   += out
            session_tokens["calls"]    += 1
            session_tokens["cost_usd"] += _price(model, inp, out)
            wid = e.get("worker_id", "")
            if wid and wid in workers:
                workers[wid]["tokens_in"]  += inp
                workers[wid]["tokens_out"] += out
                workers[wid]["model"]       = model

        # Only process worker events inside the active window
        if ts < active_cutoff:
            continue

        # ── Worker start ───────────────────────────────────────────────────
        if etype == "worker_start":
            wid = e.get("worker_id", "")
            workers[wid] = {
                "id":         wid,
                "candidate":  e.get("candidate", ""),
                "req_id":     e.get("req_id", ""),
                "client":     e.get("client", ""),
                "stage":      "queued",
                "started_at": ts,
                "elapsed_s":  0.0,
                "tokens_in":  0,
                "tokens_out": 0,
                "model":      "",
            }

        # ── Worker stage update ────────────────────────────────────────────
        elif etype == "worker_stage":
            wid = e.get("worker_id", "")
            if wid in workers:
                workers[wid]["stage"] = e.get("stage", "")

        # ── Worker complete ────────────────────────────────────────────────
        elif etype == "worker_complete":
            wid = e.get("worker_id", "")
            w = workers.pop(wid, None)
            rec = {
                "id":             wid,
                "candidate":      e.get("candidate", "") or (w or {}).get("candidate", "?"),
                "req_id":         (w or {}).get("req_id", ""),
                "score":          e.get("score"),
                "recommendation": e.get("recommendation", ""),
                "error":          e.get("error", ""),
                "completed_at":   ts,
                "elapsed_s":      round(ts - w["started_at"], 1) if w else 0,
                "tokens_in":      (w or {}).get("tokens_in", 0),
                "tokens_out":     (w or {}).get("tokens_out", 0),
                "model":          (w or {}).get("model", ""),
            }
            recent.insert(0, rec)
            completion_times.append(ts)

    # ── Throughput: 6 × 10s buckets covering the last 60 s ────────────────
    buckets = [0] * 6
    for t in completion_times:
        age = now - t
        if 0.0 <= age < 60.0:
            idx = min(5, int(age / 10))
            buckets[5 - idx] += 1

    # ── Finalise active workers ────────────────────────────────────────────
    active: list[dict] = []
    for w in workers.values():
        w["elapsed_s"] = round(now - w["started_at"], 1)
        w["cost_usd"]  = round(_price(w["model"], w["tokens_in"], w["tokens_out"]), 5)
        if w["elapsed_s"] < active_window_s:
            active.append(w)

    session_tokens["cost_usd"] = round(session_tokens["cost_usd"], 4)

    return {
        "workers":              sorted(active, key=lambda w: w["started_at"]),
        "session_tokens":       session_tokens,
        "recent":               recent[:15],
        "throughput_buckets":   buckets,
        "ts":                   now,
    }
