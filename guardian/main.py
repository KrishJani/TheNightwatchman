import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from agents.coach import coach_agent
from agents.orchestrator import TACTIC_RISK_SCORES
from agents.scribe import finalize_call, incident_log, scribe_agent
from agents.sentinel import sentinel_agent
from ingestion.simulator import SAMPLE_SCRIPT, SIMULATED_CALLER_NUMBER, simulate_call
from redis_client import (
    ALERTS_CHANNEL,
    COACHING_CHANNEL,
    TRANSCRIPT_STREAM,
    cleanup_call_data,
    create_known_scammers_filter,
    create_playbooks_vset,
    create_risk_timeline,
    create_stream,
    get_redis_client,
    is_known_scammer,
)


load_dotenv()

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


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


async def run_scribe_worker() -> None:
    while True:
        try:
            await scribe_agent()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Scribe error: {error}", flush=True)
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
    scribe_task = asyncio.create_task(run_scribe_worker())
    try:
        yield
    finally:
        for task in (sentinel_task, coach_task, scribe_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    incident_log.reset()
    await cleanup_call_data([], [])
    background_tasks.add_task(simulate_call, SAMPLE_SCRIPT)
    return {"status": "started", "entries": len(SAMPLE_SCRIPT)}


async def _send_call_history(websocket: WebSocket) -> None:
    redis = get_redis_client()
    try:
        entries = await redis.xrange(TRANSCRIPT_STREAM, min="-", max="+")
        for message_id, fields in entries:
            tactic_data = await redis.hgetall(f"guardian:tactic:{message_id}")
            if not tactic_data:
                continue

            tactic = str(tactic_data.get("tactic", "NONE")).upper()
            try:
                confidence = float(tactic_data.get("confidence", 0))
            except (TypeError, ValueError):
                confidence = 0.0

            alert = {
                "message_id": message_id,
                "text": fields.get("text", ""),
                "tactic": tactic,
                "confidence": confidence,
                "score": TACTIC_RISK_SCORES.get(tactic, 0.0),
            }
            playbook_match = tactic_data.get("playbook_match")
            if playbook_match:
                alert["playbook_match"] = playbook_match

            await websocket.send_text(json.dumps(alert))
    finally:
        await redis.aclose()


@app.post("/end-call")
async def end_call():
    return await finalize_call()


@app.get("/download-report/{timestamp}")
async def download_report(timestamp: str):
    report_path = REPORTS_DIR / f"guardian_incident_{timestamp}.pdf"
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        path=report_path,
        media_type="application/pdf",
        filename=report_path.name,
    )


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

    await _send_call_history(websocket)

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
