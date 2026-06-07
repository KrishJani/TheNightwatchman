import json
import os
import tempfile
import time

from dotenv import load_dotenv
from fastapi import UploadFile
from openai import AsyncOpenAI, BadRequestError

from redis_client import (
    TRANSCRIPT_CHANNEL,
    TRANSCRIPT_STREAM,
    create_stream,
    get_redis_client,
    record_victim_transcript_text,
    retract_caller_duplicates,
)

load_dotenv()

WHISPER_MODEL = "whisper-1"


def _get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def _write_victim_transcript(transcription: str) -> str:
    await create_stream()
    redis = get_redis_client()
    timestamp = time.time()
    try:
        message_id = await redis.xadd(
            TRANSCRIPT_STREAM,
            {
                "speaker": "victim",
                "text": transcription,
                "timestamp": timestamp,
            },
        )
        await redis.publish(
            TRANSCRIPT_CHANNEL,
            json.dumps(
                {
                    "type": "transcript",
                    "message_id": message_id,
                    "speaker": "victim",
                    "text": transcription,
                    "timestamp": timestamp,
                }
            ),
        )
        print(f"Victim transcript published {message_id}: {transcription}", flush=True)
        await record_victim_transcript_text(transcription)
        await retract_caller_duplicates(transcription)
        return message_id
    finally:
        await redis.aclose()


def _audio_suffix(filename: str, content_type: str) -> str:
    lowered_name = filename.lower()
    lowered_type = content_type.lower()
    if lowered_name.endswith(".mp4") or "mp4" in lowered_type or "m4a" in lowered_type:
        return ".mp4"
    if lowered_name.endswith(".ogg") or "ogg" in lowered_type:
        return ".ogg"
    if lowered_name.endswith(".wav") or "wav" in lowered_type:
        return ".wav"
    return ".webm"


async def transcribe_user_upload(audio: UploadFile) -> dict[str, str]:
    content = await audio.read()
    if not content or len(content) < 500:
        return {"text": ""}

    suffix = _audio_suffix(audio.filename or "", audio.content_type or "")
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        client = _get_openai_client()
        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=audio_file,
            )
        text = (transcription.text or "").strip()
    except BadRequestError as error:
        print(f"Victim transcription rejected by Whisper: {error}", flush=True)
        return {"text": ""}
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

    if text:
        await _write_victim_transcript(text)

    return {"text": text}
