import json
import os
import time
from typing import Any

import weave
from dotenv import load_dotenv
from openai import AsyncOpenAI

from agents.orchestrator import update_risk_score
from redis_client import AGENTS_GROUP, TRANSCRIPT_STREAM, create_stream, get_redis_client


CONSUMER_NAME = "sentinel"
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
TACTICS = {
    "URGENCY",
    "AUTHORITY_IMPERSONATION",
    "FEAR",
    "SECRECY",
    "GIFT_CARD_REQUEST",
    "WIRE_REQUEST",
    "NONE",
}

SYSTEM_PROMPT = """
Classify the scam manipulation tactic in the utterance.

Return only JSON with:
- tactic: one of URGENCY, AUTHORITY_IMPERSONATION, FEAR, SECRECY,
  GIFT_CARD_REQUEST, WIRE_REQUEST, NONE
- confidence: number from 0 to 1
""".strip()


load_dotenv()
INFERENCE_BASE_URL = os.getenv(
    "WANDB_BASE_URL",
    "https://api.inference.wandb.ai/v1",
)

# WANDB_BASE_URL is used here for the OpenAI-compatible inference endpoint.
# The Weave SDK also reads that env var for its own GraphQL API, so keep it
# out of the environment while initializing tracing.
_wandb_base_url = os.environ.pop("WANDB_BASE_URL", None)
try:
    weave.init("guardian")
finally:
    if _wandb_base_url is not None:
        os.environ["WANDB_BASE_URL"] = _wandb_base_url


def _get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.getenv("WANDB_API_KEY"),
        base_url=INFERENCE_BASE_URL,
    )


def _parse_classification(content: str) -> dict[str, str]:
    json_start = content.find("{")
    json_end = content.rfind("}")
    if json_start != -1 and json_end != -1:
        content = content[json_start : json_end + 1]

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {"tactic": "NONE", "confidence": "0.0"}

    tactic = str(payload.get("tactic", "NONE")).upper()
    if tactic not in TACTICS:
        tactic = "NONE"

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = min(max(confidence, 0.0), 1.0)
    return {"tactic": tactic, "confidence": str(confidence)}


def _fallback_classification(message: dict[str, Any]) -> dict[str, str]:
    text = message.get("text", "").lower()

    if "gift card" in text or "apple gift" in text or "read me the numbers" in text:
        return {"tactic": "GIFT_CARD_REQUEST", "confidence": "0.95"}
    if "wire" in text or "western union" in text or "moneygram" in text:
        return {"tactic": "WIRE_REQUEST", "confidence": "0.9"}
    if "police" in text or "officer" in text or "judge" in text or "courthouse" in text:
        return {"tactic": "AUTHORITY_IMPERSONATION", "confidence": "0.8"}
    if "don't tell" in text or "quietly" in text or "not to tell" in text:
        return {"tactic": "SECRECY", "confidence": "0.8"}
    if "today" in text or "right now" in text or "weekend in jail" in text:
        return {"tactic": "URGENCY", "confidence": "0.75"}
    if "jail" in text or "accident" in text or "hurt" in text:
        return {"tactic": "FEAR", "confidence": "0.7"}

    return {"tactic": "NONE", "confidence": "0.1"}


def _apply_payment_overrides(
    message: dict[str, Any],
    classification: dict[str, str],
) -> dict[str, str]:
    fallback = _fallback_classification(message)
    if fallback["tactic"] in {"GIFT_CARD_REQUEST", "WIRE_REQUEST"}:
        return fallback

    return classification


@weave.op()
async def _classify_utterance(message: dict[str, Any]) -> dict[str, str]:
    client = _get_llm_client()
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Speaker: {message.get('speaker', 'unknown')}\n"
                    f"Utterance: {message.get('text', '')}"
                ),
            },
        ],
        temperature=0,
        max_tokens=60,
    )

    content = response.choices[0].message.content or "{}"
    return _parse_classification(content)


async def sentinel_agent(state: dict[str, Any] | None = None) -> dict[str, Any]:
    await create_stream()

    redis = get_redis_client()
    processed: list[dict[str, str]] = []

    try:
        streams = await redis.xreadgroup(
            groupname=AGENTS_GROUP,
            consumername=CONSUMER_NAME,
            streams={TRANSCRIPT_STREAM: "0"},
            count=10,
        )
        if not any(messages for _, messages in streams):
            streams = await redis.xreadgroup(
                groupname=AGENTS_GROUP,
                consumername=CONSUMER_NAME,
                streams={TRANSCRIPT_STREAM: ">"},
                count=10,
                block=1000,
            )

        for _, messages in streams:
            for message_id, message in messages:
                try:
                    classification = await _classify_utterance(message)
                except Exception as error:
                    print(
                        f"Sentinel LLM error for {message_id}: {error}; "
                        "using fallback classifier",
                        flush=True,
                    )
                    classification = _fallback_classification(message)

                classification = _apply_payment_overrides(message, classification)
                tactic_key = f"guardian:tactic:{message_id}"

                await redis.hset(
                    tactic_key,
                    mapping={
                        **classification,
                        "message_id": message_id,
                        "processed_at": str(time.time()),
                    },
                )
                await update_risk_score(
                    message_id,
                    classification["tactic"],
                    float(classification["confidence"]),
                )
                await redis.xack(TRANSCRIPT_STREAM, AGENTS_GROUP, message_id)
                print(
                    "Sentinel processed "
                    f"{message_id}: {classification['tactic']} "
                    f"({classification['confidence']})",
                    flush=True,
                )
                processed.append(
                    {
                        "message_id": message_id,
                        **classification,
                    }
                )
    finally:
        await redis.aclose()

    return {
        **(state or {}),
        "sentinel_processed": len(processed),
        "sentinel_results": processed,
    }
