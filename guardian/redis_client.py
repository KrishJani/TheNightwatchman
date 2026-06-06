import os

from redis.asyncio import Redis
from redis.exceptions import ResponseError


TRANSCRIPT_STREAM = "guardian:transcript"
AGENTS_GROUP = "agents"
RISK_TIMELINE = "guardian:risk_timeline"
ALERTS_CHANNEL = "guardian:alerts"


def get_redis_client() -> Redis:
    return Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


async def create_stream() -> None:
    redis = get_redis_client()
    try:
        await redis.xgroup_create(
            name=TRANSCRIPT_STREAM,
            groupname=AGENTS_GROUP,
            id="0",
            mkstream=True,
        )
    except ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise
    finally:
        await redis.aclose()


async def create_risk_timeline() -> None:
    redis = get_redis_client()
    try:
        if await redis.exists(RISK_TIMELINE):
            return

        await redis.ts().create(RISK_TIMELINE)
    except ResponseError as error:
        if "already exists" not in str(error).lower():
            raise
    finally:
        await redis.aclose()
