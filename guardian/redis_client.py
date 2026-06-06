import os

from redis.asyncio import Redis
from redis.exceptions import ResponseError


TRANSCRIPT_STREAM = "guardian:transcript"
AGENTS_GROUP = "agents"
RISK_TIMELINE = "guardian:risk_timeline"
ALERTS_CHANNEL = "guardian:alerts"
COACHING_CHANNEL = "guardian:coaching"
KNOWN_SCAMMERS_FILTER = "guardian:known_scammers"
SEED_SCAMMER_NUMBERS = [
    "14155551234",
    "18005559999",
    "12125550000",
    "19175551111",
    "16505558888",
]


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


async def create_known_scammers_filter() -> None:
    redis = get_redis_client()
    try:
        try:
            await redis.execute_command(
                "BF.RESERVE",
                KNOWN_SCAMMERS_FILTER,
                0.001,
                10000,
            )
        except ResponseError as error:
            if "item exists" not in str(error).lower():
                raise

        for phone_number in SEED_SCAMMER_NUMBERS:
            await redis.execute_command("BF.ADD", KNOWN_SCAMMERS_FILTER, phone_number)
    finally:
        await redis.aclose()


async def add_scammer(phone_number: str) -> None:
    redis = get_redis_client()
    try:
        await redis.execute_command("BF.ADD", KNOWN_SCAMMERS_FILTER, phone_number)
    finally:
        await redis.aclose()


async def is_known_scammer(phone_number: str) -> bool:
    redis = get_redis_client()
    try:
        return bool(
            await redis.execute_command("BF.EXISTS", KNOWN_SCAMMERS_FILTER, phone_number)
        )
    finally:
        await redis.aclose()
