import json
import time

from redis_client import ALERTS_CHANNEL, RISK_TIMELINE, TRANSCRIPT_STREAM, get_redis_client


TACTIC_RISK_SCORES = {
    "NONE": 0.0,
    "URGENCY": 0.3,
    "FEAR": 0.3,
    "AUTHORITY_IMPERSONATION": 0.5,
    "SECRECY": 0.6,
    "WIRE_REQUEST": 0.9,
    "GIFT_CARD_REQUEST": 1.0,
}


async def update_risk_score(
    message_id: str,
    tactic: str,
    confidence: float,
) -> dict[str, str | float]:
    redis = get_redis_client()

    try:
        tactic_result = await redis.hgetall(f"guardian:tactic:{message_id}")
        resolved_tactic = tactic_result.get("tactic", tactic).upper()

        try:
            resolved_confidence = float(tactic_result.get("confidence", confidence))
        except (TypeError, ValueError):
            resolved_confidence = confidence

        score = TACTIC_RISK_SCORES.get(resolved_tactic, 0.0)
        timestamp_ms = int(time.time() * 1000)

        await redis.ts().add(RISK_TIMELINE, timestamp_ms, score)

        stream_entries = await redis.xrange(
            TRANSCRIPT_STREAM,
            min=message_id,
            max=message_id,
            count=1,
        )
        utterance_text = stream_entries[0][1].get("text", "") if stream_entries else ""

        alert = {
            "message_id": message_id,
            "tactic": resolved_tactic,
            "confidence": resolved_confidence,
            "score": score,
            "text": utterance_text,
        }
        playbook_match = tactic_result.get("playbook_match")
        if playbook_match:
            alert["playbook_match"] = playbook_match
        await redis.publish(ALERTS_CHANNEL, json.dumps(alert))
    finally:
        await redis.aclose()

    return alert
