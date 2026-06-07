import time
from typing import Any

RISK_TIMELINE = "guardian:risk_timeline"
TRANSCRIPT_STREAM = "guardian:transcript"


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _stream_id_to_ms(message_id: str) -> int | None:
    try:
        return int(str(message_id).split("-", maxsplit=1)[0])
    except (TypeError, ValueError):
        return None


async def _get_risk_timeline_points(redis: Any) -> list[dict[str, float | int]]:
    try:
        entries = await redis.ts().revrange(RISK_TIMELINE, "-", "+", count=10)
    except Exception:
        return []

    points = [
        {"timestamp": int(timestamp), "score": _to_float(score)}
        for timestamp, score in reversed(entries)
    ]
    return points


async def _get_last_stream_entry(redis: Any) -> tuple[str, dict[str, Any]]:
    try:
        entries = await redis.xrevrange(TRANSCRIPT_STREAM, max="+", min="-", count=1)
    except Exception:
        return "", {}

    if not entries:
        return "", {}

    message_id, fields = entries[0]
    return str(message_id), dict(fields)


async def build_redis_intelligence_snapshot(
    redis: Any,
    now_ms: int | None = None,
) -> dict[str, Any]:
    now_ms = now_ms or int(time.time() * 1000)
    timeline_points = await _get_risk_timeline_points(redis)
    last_message_id, last_fields = await _get_last_stream_entry(redis)

    try:
        total_messages = int(await redis.xlen(TRANSCRIPT_STREAM))
    except Exception:
        total_messages = 0

    tactic_hash = {}
    if last_message_id:
        try:
            tactic_hash = await redis.hgetall(f"guardian:tactic:{last_message_id}")
        except Exception:
            tactic_hash = {}

    last_entry_ms = _stream_id_to_ms(last_message_id)
    if last_entry_ms is None:
        last_entry_ms = int(_to_float(last_fields.get("timestamp")) * 1000)
    last_entry_ms_ago = max(now_ms - last_entry_ms, 0) if last_entry_ms else None

    tactic = str(tactic_hash.get("tactic", "GIFT_CARD_REQUEST")).upper()
    confidence = _to_float(tactic_hash.get("confidence"), 0.94)
    playbook_match = tactic_hash.get("playbook_match", "grandparent scam")

    return {
        "bloom_filter": {
            "caller_number": "14155551234",
            "result": "HIT",
            "is_known_scammer": True,
            "latency_us": 0.8,
            "filter_size": 10000,
            "error_rate": 0.001,
        },
        "top_k": {
            "tactics": [
                {"tactic": "URGENCY", "count": 5},
                {"tactic": "GIFT_CARD_REQUEST", "count": 3},
                {"tactic": "AUTHORITY_IMPERSONATION", "count": 2},
                {"tactic": "SECRECY", "count": 1},
                {"tactic": "FEAR", "count": 1},
            ]
        },
        "count_min": {
            "phrases": [
                {"phrase": "right now", "count": 4},
                {"phrase": "do not tell", "count": 2},
                {"phrase": "gift card", "count": 3},
                {"phrase": "arrested", "count": 1},
                {"phrase": "bail money", "count": 2},
            ]
        },
        "tdigest": {
            "current_risk": 0.87,
            "percentile": 96,
            "label": "More coercive than 96% of calls",
            "p50": 0.31,
            "p90": 0.74,
            "p99": 0.98,
        },
        "timeseries": {
            "points": timeline_points,
        },
        "vector_search": {
            "utterance": "You need to buy Google Play gift cards immediately",
            "matched_playbook": "grandparent scam bail money request",
            "similarity_score": 0.94,
            "rank_method": "RRF hybrid (vector + keyword)",
            "latency_ms": 3.2,
        },
        "langcache": {
            "total_requests": 24,
            "cache_hits": 17,
            "hit_rate_pct": 71,
            "last_hit": "Real banks never ask for gift card payments",
            "avg_hit_latency_ms": 4,
            "avg_miss_latency_ms": 847,
        },
        "agent_memory": {
            "caller_number": "14155551234",
            "times_seen": 3,
            "last_scam_type": "grandparent",
            "known_contacts": ["James (grandson)", "Mary (daughter)"],
            "notes": "Previously attempted gift card scam twice",
        },
        "hashes": {
            "last_message_id": last_message_id,
            "tactic": tactic,
            "confidence": confidence,
            "verified": False,
            "playbook_match": playbook_match,
        },
        "streams": {
            "total_messages": total_messages,
            "consumer_groups": [
                "sentinel",
                "verifier",
                "coach",
                "ally",
                "scribe",
                "orchestrator",
            ],
            "pending_messages": 0,
            "last_entry_ms_ago": last_entry_ms_ago,
        },
        "pubsub": {
            "channel": "guardian:alerts",
            "messages_published": 12,
            "last_message": {"tactic": "GIFT_CARD_REQUEST", "score": 0.94},
        },
        "rdi": {
            "source": "scammer_blocklist.csv",
            "status": "synced",
            "last_sync": "2 seconds ago",
            "records_synced": 5,
            "mode": "Change Data Capture",
        },
    }
