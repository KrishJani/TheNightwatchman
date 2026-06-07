import asyncio
import json
import os
import re
import time
from typing import Any

import weave
from dotenv import load_dotenv
from openai import AsyncOpenAI

from redis_client import ALERTS_CHANNEL, VERIFICATION_CHANNEL, get_redis_client


MODEL_NAME = "meta-llama/Llama-3.3-70B-Instruct"
TARGET_TACTICS = {"AUTHORITY_IMPERSONATION", "FEAR"}
SYSTEM_PROMPT = (
    "You are a fact-checking assistant. Given this claim made during a phone call, "
    "assess its credibility based on known scam patterns and general knowledge. "
    "Output JSON with fields: claim (what was claimed), verdict (CREDIBLE / "
    "SUSPICIOUS / UNVERIFIABLE), reason (one sentence explanation), "
    "red_flag (true/false)"
)

CHECKABLE_CLAIM_PATTERNS = [
    re.compile(
        r"\b(?:officer|agent|detective|sergeant|lieutenant|inspector|"
        r"special agent|deputy)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:I'm|I am|this is|my name is)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
        re.IGNORECASE,
    ),
    re.compile(r"\bbadge\s*(?:number|#|no\.?)?\s*#?\d", re.IGNORECASE),
    re.compile(
        r"\b(?:IRS|FBI|CIA|DEA|SSA|Social Security|Medicare|Medicaid|Treasury|"
        r"courthouse|police department|sheriff(?:'s)? office|county police|"
        r"Wells Fargo|Chase|Bank of America|Citibank|Capital One)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:account|routing|case|confirmation|reference|social security|SSN)\s*"
        r"(?:number|#|no\.?)?\s*#?\d",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(
        r"\b(?:account|case)\s+(?:ending in|number)\s+\d",
        re.IGNORECASE,
    ),
]
VERDICTS = {"CREDIBLE", "SUSPICIOUS", "UNVERIFIABLE"}


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


def _has_checkable_claim(text: str) -> bool:
    return any(pattern.search(text) for pattern in CHECKABLE_CLAIM_PATTERNS)


def _parse_verification(content: str, utterance: str) -> dict[str, Any]:
    json_start = content.find("{")
    json_end = content.rfind("}")
    if json_start != -1 and json_end != -1:
        content = content[json_start : json_end + 1]

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {
            "claim": utterance,
            "verdict": "UNVERIFIABLE",
            "reason": "Could not assess the claim automatically.",
            "red_flag": "true",
        }

    verdict = str(payload.get("verdict", "UNVERIFIABLE")).upper()
    if verdict not in VERDICTS:
        verdict = "UNVERIFIABLE"

    red_flag = payload.get("red_flag", verdict != "CREDIBLE")
    if isinstance(red_flag, str):
        red_flag = red_flag.lower() in {"true", "1", "yes"}
    else:
        red_flag = bool(red_flag)

    return {
        "claim": str(payload.get("claim", utterance)),
        "verdict": verdict,
        "reason": str(payload.get("reason", "")),
        "red_flag": str(red_flag).lower(),
    }


def _fallback_verification(utterance: str, tactic: str) -> dict[str, Any]:
    if tactic == "AUTHORITY_IMPERSONATION":
        return {
            "claim": utterance,
            "verdict": "SUSPICIOUS",
            "reason": "Authority impersonation claims are a common scam tactic.",
            "red_flag": "true",
        }

    return {
        "claim": utterance,
        "verdict": "UNVERIFIABLE",
        "reason": "Fear-based claims during calls should be verified independently.",
        "red_flag": "true",
    }


@weave.op()
async def _verify_claim(alert: dict[str, Any]) -> dict[str, Any]:
    utterance = str(alert.get("text", ""))
    client = _get_llm_client()
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Tactic: {alert.get('tactic', 'UNKNOWN')}\n"
                    f"Utterance: {utterance}"
                ),
            },
        ],
        temperature=0,
        max_tokens=120,
    )

    content = response.choices[0].message.content or "{}"
    return _parse_verification(content, utterance)


async def _handle_alert(alert: dict[str, Any]) -> dict[str, Any] | None:
    tactic = str(alert.get("tactic", "NONE")).upper()
    if tactic not in TARGET_TACTICS:
        return None

    utterance = str(alert.get("text", ""))
    if not _has_checkable_claim(utterance):
        return None

    message_id = str(alert.get("message_id", ""))
    if not message_id:
        return None

    try:
        verification = await _verify_claim(alert)
    except Exception as error:
        print(f"Verifier LLM error for {message_id}: {error}; using fallback", flush=True)
        verification = _fallback_verification(utterance, tactic)

    redis = get_redis_client()
    try:
        verification_key = f"guardian:verification:{message_id}"
        stored_fields = {
            **verification,
            "message_id": message_id,
            "tactic": tactic,
            "processed_at": str(time.time()),
        }
        await redis.hset(verification_key, mapping=stored_fields)

        payload = {
            "type": "verification_result",
            "message_id": message_id,
            **verification,
        }
        await redis.publish(VERIFICATION_CHANNEL, json.dumps(payload))
    finally:
        await redis.aclose()

    print(
        f"Verifier processed {message_id}: {verification['verdict']} "
        f"({verification['claim'][:60]})",
        flush=True,
    )
    return payload


async def verifier_agent() -> None:
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
