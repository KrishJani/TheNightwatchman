import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, WebSocket, WebSocketDisconnect

from agents.coach import coach_agent
from agents.sentinel import sentinel_agent
from ingestion.simulator import SAMPLE_SCRIPT, SIMULATED_CALLER_NUMBER, simulate_call
from redis_client import (
    ALERTS_CHANNEL,
    COACHING_CHANNEL,
    create_known_scammers_filter,
    create_playbooks_vset,
    create_risk_timeline,
    create_stream,
    get_redis_client,
    is_known_scammer,
)


load_dotenv()


async def run_sentinel_worker() -> None:
    while True:
        try:
            result = await sentinel_agent()
            if result["sentinel_processed"] == 0:
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Sentinel error: {error}", flush=True)
            await asyncio.sleep(1)


async def run_coach_worker() -> None:
    while True:
        try:
            await coach_agent()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Coach error: {error}", flush=True)
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Guardian starting", flush=True)
    await create_stream()
    await create_risk_timeline()
    await create_known_scammers_filter()
    await create_playbooks_vset()
    sentinel_task = asyncio.create_task(run_sentinel_worker())
    coach_task = asyncio.create_task(run_coach_worker())
    try:
        yield
    finally:
        for task in (sentinel_task, coach_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    redis = get_redis_client()
    try:
        await redis.ping()
    except Exception as error:
        return {"status": "error", "detail": str(error)}
    finally:
        await redis.aclose()

    return {"status": "ok"}


@app.post("/simulate")
async def simulate(background_tasks: BackgroundTasks):
    background_tasks.add_task(simulate_call, SAMPLE_SCRIPT)
    return {"status": "started", "entries": len(SAMPLE_SCRIPT)}


@app.websocket("/ws")
async def websocket_alerts(websocket: WebSocket):
    await websocket.accept()

    if await is_known_scammer(SIMULATED_CALLER_NUMBER):
        await websocket.send_json(
            {
                "type": "known_scammer",
                "message": "This number has been reported for scam calls",
            }
        )

    redis = get_redis_client()
    pubsub = redis.pubsub()

    try:
        await pubsub.subscribe(ALERTS_CHANNEL, COACHING_CHANNEL)

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1,
            )
            if message is None:
                continue

            if message["type"] != "message":
                continue

            await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(ALERTS_CHANNEL, COACHING_CHANNEL)
        await pubsub.aclose()
        await redis.aclose()
