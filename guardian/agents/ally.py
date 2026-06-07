import asyncio
import json
import os
from typing import Any

import weave
from dotenv import load_dotenv
from openai import AsyncOpenAI

from agents.orchestrator import TACTIC_RISK_SCORES
from redis_client import (
    ALLY_ALERT_KEY,
    ALLY_CHANNEL,
    RISK_TIMELINE,
    TRANSCRIPT_STREAM,
    get_redis_client,
)


MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
CHECK_INTERVAL_SECONDS = 20
RISK_WINDOW_SIZE = 4
RISK_AVERAGE_THRESHOLD = 0.7


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


def _build_system_prompt(tactic: str) -> str:
    return (
        "Write a short, calm SMS alert (max 2 sentences) to a trusted family member. "
        "Tell them their loved one has been on a suspicious call for several minutes and "
        "suggest they check in. Do not cause panic. "
        f"Mention the top detected tactic: {tactic}"
    )


def _fallback_alert(tactic: str) -> str:
    readable_tactic = tactic.replace("_", " ").lower()
    return (
        "Hi, this is a Guardian alert. Your loved one may be on a suspicious call "
        f"involving {readable_tactic}. Please check in with them when you can."
    )


async def _get_top_tactic(redis: Any) -> str:
    top_tactic = "UNKNOWN"
    top_score = -1.0

    entries = await redis.xrange(TRANSCRIPT_STREAM, min="-", max="+")
    for message_id, _ in entries:
        tactic_data = await redis.hgetall(f"guardian:tactic:{message_id}")
        tactic = str(tactic_data.get("tactic", "NONE")).upper()
        score = TACTIC_RISK_SCORES.get(tactic, 0.0)
        if score > top_score:
            top_score = score
            top_tactic = tactic

    if top_tactic in {"NONE", "UNKNOWN"}:
        return "suspicious activity"

    return top_tactic.replace("_", " ").lower()


@weave.op()
async def _generate_ally_alert(tactic: str) -> str:
    client = _get_llm_client()
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": _build_system_prompt(tactic)},
            {"role": "user", "content": "Write the SMS alert now."},
        ],
        temperature=0.2,
        max_tokens=80,
    )
    return (response.choices[0].message.content or "").strip().strip('"')


async def _check_risk_timeline() -> None:
    redis = get_redis_client()
    try:
        if await redis.exists(ALLY_ALERT_KEY):
            return

        entries = await redis.ts().revrange(
            RISK_TIMELINE,
            "-",
            "+",
            count=RISK_WINDOW_SIZE,
        )
        if len(entries) < RISK_WINDOW_SIZE:
            return

        scores = [float(value) for _, value in entries]
        average_score = sum(scores) / len(scores)
        if average_score <= RISK_AVERAGE_THRESHOLD:
            return

        top_tactic = await _get_top_tactic(redis)
        try:
            alert_message = await _generate_ally_alert(top_tactic)
        except Exception as error:
            print(f"Ally LLM error: {error}; using fallback alert", flush=True)
            alert_message = _fallback_alert(top_tactic)

        if not alert_message:
            alert_message = _fallback_alert(top_tactic)

        await redis.set(ALLY_ALERT_KEY, alert_message)

        payload = {
            "type": "ally_alert",
            "message": alert_message,
        }
        await redis.publish(ALLY_CHANNEL, json.dumps(payload))
        print(
            f"Ally alert activated (avg risk {average_score:.2f}): {alert_message}",
            flush=True,
        )
    finally:
        await redis.aclose()


async def ally_agent() -> None:
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        try:
            await _check_risk_timeline()
        except Exception as error:
            print(f"Ally check error: {error}", flush=True)
