import json
import os

from openai import AsyncOpenAI
from redis.asyncio import Redis
from redis.exceptions import ResponseError


TRANSCRIPT_STREAM = "guardian:transcript"
AGENTS_GROUP = "agents"
RISK_TIMELINE = "guardian:risk_timeline"
ALERTS_CHANNEL = "guardian:alerts"
COACHING_CHANNEL = "guardian:coaching"
KNOWN_SCAMMERS_FILTER = "guardian:known_scammers"
PLAYBOOKS_VSET = "guardian:playbooks"
EMBEDDING_MODEL = "text-embedding-3-small"
PLAYBOOK_SIMILARITY_THRESHOLD = 0.75
SEED_SCAMMER_NUMBERS = [
    "14155551234",
    "18005559999",
    "12125550000",
    "19175551111",
    "16505558888",
]
SCAM_PLAYBOOKS = [
    {
        "key": "grandparent_scam",
        "name": "grandparent scam",
        "description": "grandparent scam bail money request",
    },
    {
        "key": "irs_tax_scam",
        "name": "IRS tax scam",
        "description": "IRS threatening arrest for unpaid taxes",
    },
    {
        "key": "bank_fraud_scam",
        "name": "bank fraud scam",
        "description": "bank fraud account compromised urgent",
    },
    {
        "key": "prize_winning_scam",
        "name": "prize winning scam",
        "description": "prize winning fee required upfront",
    },
    {
        "key": "romance_scam",
        "name": "romance scam",
        "description": "romance scam wire transfer request",
    },
    {
        "key": "tech_support_scam",
        "name": "tech support scam",
        "description": "tech support remote access request",
    },
    {
        "key": "utility_shutoff_scam",
        "name": "utility shutoff scam",
        "description": "utility shutoff immediate payment",
    },
    {
        "key": "crypto_investment_scam",
        "name": "crypto investment scam",
        "description": "crypto investment guaranteed returns",
    },
]
PLAYBOOK_NAME_BY_KEY = {playbook["key"]: playbook["name"] for playbook in SCAM_PLAYBOOKS}


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


def _get_embedding_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def embed_text(text: str) -> list[float]:
    client = _get_embedding_client()
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def _parse_vsim_top_result(result: object) -> tuple[str | None, float]:
    if not result:
        return None, 0.0

    if isinstance(result, dict):
        key = next(iter(result))
        return key, float(result[key])

    if isinstance(result, list) and len(result) >= 2:
        return str(result[0]), float(result[1])

    if isinstance(result, list) and len(result) == 1:
        return str(result[0]), 0.0

    return None, 0.0


async def create_playbooks_vset() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print("Skipping playbook seeding: OPENAI_API_KEY is not set", flush=True)
        return

    redis = get_redis_client()
    try:
        try:
            existing_count = int(await redis.execute_command("VCARD", PLAYBOOKS_VSET))
        except ResponseError:
            existing_count = 0

        if existing_count >= len(SCAM_PLAYBOOKS):
            return

        for playbook in SCAM_PLAYBOOKS:
            embedding = await embed_text(playbook["description"])
            await redis.execute_command(
                "VADD",
                PLAYBOOKS_VSET,
                "VALUES",
                len(embedding),
                *[str(value) for value in embedding],
                playbook["key"],
                "SETATTR",
                json.dumps(
                    {
                        "name": playbook["name"],
                        "description": playbook["description"],
                    }
                ),
            )

        print(f"Seeded {len(SCAM_PLAYBOOKS)} scam playbooks into {PLAYBOOKS_VSET}", flush=True)
    finally:
        await redis.aclose()


async def search_playbook_match(text: str) -> str | None:
    if not text.strip() or not os.getenv("OPENAI_API_KEY"):
        return None

    embedding = await embed_text(text)
    redis = get_redis_client()
    try:
        result = await redis.execute_command(
            "VSIM",
            PLAYBOOKS_VSET,
            "VALUES",
            len(embedding),
            *[str(value) for value in embedding],
            "WITHSCORES",
            "COUNT",
            1,
        )
        matched_key, score = _parse_vsim_top_result(result)
        if matched_key is None or score < PLAYBOOK_SIMILARITY_THRESHOLD:
            return None

        return PLAYBOOK_NAME_BY_KEY.get(matched_key, matched_key.replace("_", " "))
    finally:
        await redis.aclose()


async def cleanup_call_data(
    message_ids: list[str],
    risk_timestamps_ms: list[int],
) -> None:
    redis = get_redis_client()
    try:
        ids_to_delete = list(message_ids)
        if not ids_to_delete:
            stream_entries = await redis.xrange(TRANSCRIPT_STREAM, min="-", max="+")
            ids_to_delete = [entry_id for entry_id, _ in stream_entries]

        for message_id in ids_to_delete:
            await redis.xdel(TRANSCRIPT_STREAM, message_id)
            await redis.delete(f"guardian:tactic:{message_id}")

        if risk_timestamps_ms:
            await redis.ts().delete(
                RISK_TIMELINE,
                min(risk_timestamps_ms),
                max(risk_timestamps_ms),
            )
    finally:
        await redis.aclose()
