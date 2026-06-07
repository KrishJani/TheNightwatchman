import asyncio
import json
import os
from typing import Any

import weave
from dotenv import load_dotenv
from openai import AsyncOpenAI

from redis_client import ALERTS_CHANNEL, COACHING_CHANNEL, get_redis_client


MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
RISK_THRESHOLD = 0.6
SYSTEM_PROMPT = (
    "You are a protective assistant helping a vulnerable person on a scam call. "
    "Given the detected tactic, generate one short, calm sentence they can say "
    "to buy time or safely end the call. Never alarm them. Max 15 words."
)


load_dotenv()
INFERENCE_BASE_URL = os.getenv(
    "WANDB_BASE_URL",
    "https://api.inference.wandb.ai/v1",
)

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


def _fallback_tip(tactic: str) -> str:
    if tactic in {"GIFT_CARD_REQUEST", "WIRE_REQUEST"}:
        return "I need to verify this with my family before sending anything."
    if tactic == "AUTHORITY_IMPERSONATION":
        return "Please give me your badge number and a callback number."
    if tactic == "SECRECY":
        return "I am going to pause and talk this over with someone I trust."
    if tactic in {"URGENCY", "FEAR"}:
        return "I need a moment to think before I make any decisions."

    return "I will call back after I verify this information."


@weave.op()
async def _generate_coaching_tip(alert: dict[str, Any]) -> str:
    client = _get_llm_client()
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Tactic: {alert.get('tactic', 'UNKNOWN')}\n"
                    f"Original utterance: {alert.get('text', '')}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=40,
    )
    return (response.choices[0].message.content or "").strip().strip('"')


async def _handle_alert(alert: dict[str, Any]) -> dict[str, Any] | None:
    score = float(alert.get("score", 0))
    if score <= RISK_THRESHOLD:
        return None

    tactic = str(alert.get("tactic", "UNKNOWN"))
    try:
        tip = await _generate_coaching_tip(alert)
    except Exception as error:
        print(f"Coach LLM error: {error}; using fallback tip", flush=True)
        tip = _fallback_tip(tactic)

    payload = {
        "type": "coaching_tip",
        "message_id": alert.get("message_id"),
        "tactic": tactic,
        "tip": tip,
    }

    redis = get_redis_client()
    try:
        await redis.publish(COACHING_CHANNEL, json.dumps(payload))
    finally:
        await redis.aclose()

    print(f"Coach published tip for {payload['message_id']}: {tip}", flush=True)
    return payload


async def coach_agent() -> None:
    redis = get_redis_client()
    pubsub = redis.pubsub()

    try:
        await pubsub.subscribe(ALERTS_CHANNEL)

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1,
            )
            if message is None or message["type"] != "message":
                continue

            alert = json.loads(message["data"])
            asyncio.create_task(_handle_alert(alert))
    finally:
        await pubsub.unsubscribe(ALERTS_CHANNEL)
        await pubsub.aclose()
        await redis.aclose()
