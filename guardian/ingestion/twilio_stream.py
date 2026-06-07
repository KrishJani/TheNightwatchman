import array
import asyncio
import base64
import json
import math
import os
import re
import tempfile
import time
import traceback
import wave
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from openai import AsyncOpenAI
from twilio.twiml.voice_response import Start, VoiceResponse

from redis_client import TRANSCRIPT_CHANNEL, TRANSCRIPT_STREAM, create_stream, get_redis_client

try:
    import audioop
except ModuleNotFoundError:
    audioop = None


load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
WHISPER_MODEL = "whisper-1"
# Lower flush interval => speech reaches the console sooner. ~2s still gives
# Whisper enough audio for a usable transcription.
AUDIO_FLUSH_SECONDS = 2
MIN_TRANSCRIPT_WORDS = 3
# A short fragment is held at most this many flush cycles before being
# published anyway, so slow/short speech never gets stuck waiting for more.
MAX_PENDING_FLUSH_CYCLES = 1
MULAW_SAMPLE_RATE = 8000
PCM_SAMPLE_WIDTH = 2
SCAM_TRANSCRIPT_KEYWORDS = {
    "arrest",
    "arrested",
    "bail",
    "bond",
    "gift card",
    "google play",
    "apple gift",
    "jail",
    "police",
    "officer",
    "urgent",
}
# Below this RMS amplitude a chunk is treated as silence/line noise and never
# sent to Whisper. Whisper invents text ("Bye.", "Thank you.") on near-silence,
# so skipping these chunks removes phantom transcript lines at the source.
SILENCE_RMS_THRESHOLD = 220
# Phrases Whisper commonly hallucinates over silence or background noise.
# Compared after lowercasing and stripping punctuation.
WHISPER_HALLUCINATIONS = {
    "",
    "you",
    "thank you",
    "thank you very much",
    "thank you for watching",
    "thanks",
    "thanks for watching",
    "bye",
    "bye bye",
    "goodbye",
    "okay",
    "ok",
    "uh",
    "um",
    "hmm",
    "mm",
    "mhm",
    "mm hmm",
    "yeah",
    "so",
    "the",
    "please subscribe",
    "subscribe",
    "music",
    "silence",
}


def _get_media_ws_url() -> str:
    load_dotenv(override=True)
    configured_ngrok_url = os.getenv("NGROK_URL", "")
    ngrok_url = configured_ngrok_url.strip().rstrip("/")
    if not ngrok_url:
        raise ValueError("Set NGROK_URL to your bare ngrok domain")

    parsed = urlparse(ngrok_url)
    host = parsed.netloc or parsed.path
    if not host:
        raise ValueError(f"Invalid NGROK_URL: {configured_ngrok_url}")

    return f"wss://{host}/twilio/media"


def build_incoming_twiml() -> str:
    response = VoiceResponse()
    start = Start()
    start.stream(url=_get_media_ws_url(), track="inbound_track")
    response.append(start)
    response.say("Guardian is listening.")
    response.pause(length=3600)
    return str(response)


async def handle_twilio_incoming() -> Response:
    try:
        twiml = build_incoming_twiml()
        print("Twilio incoming call: returning Media Stream TwiML", flush=True)
        print(twiml, flush=True)
        return Response(content=twiml, media_type="application/xml")
    except Exception as error:
        print(f"Twilio incoming call error: {error}", flush=True)
        traceback.print_exc()

        response = VoiceResponse()
        response.say("Guardian is temporarily unable to start call monitoring.")
        twiml = str(response)
        print("Twilio incoming call fallback TwiML:", flush=True)
        print(twiml, flush=True)
        return Response(content=twiml, media_type="application/xml")


def _get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _decode_mulaw_byte(sample: int) -> int:
    sample = ~sample & 0xFF
    sign = sample & 0x80
    exponent = (sample >> 4) & 0x07
    mantissa = sample & 0x0F
    value = ((mantissa << 3) + 0x84) << exponent
    value -= 0x84
    return -value if sign else value


def _mulaw_to_pcm(mulaw_audio: bytes) -> bytes:
    if audioop is not None:
        return audioop.ulaw2lin(mulaw_audio, PCM_SAMPLE_WIDTH)

    pcm = bytearray()
    for sample in mulaw_audio:
        pcm.extend(_decode_mulaw_byte(sample).to_bytes(2, "little", signed=True))
    return bytes(pcm)


def _write_wav_file(pcm_audio: bytes) -> str:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp_path = temp_file.name
    temp_file.close()

    with wave.open(temp_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(PCM_SAMPLE_WIDTH)
        wav_file.setframerate(MULAW_SAMPLE_RATE)
        wav_file.writeframes(pcm_audio)

    return temp_path


async def _transcribe_wav_file(wav_path: str) -> str:
    client = _get_openai_client()
    with open(wav_path, "rb") as audio_file:
        transcription = await client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=audio_file,
        )
    return (transcription.text or "").strip()


async def _write_transcript(transcription: str, caller_number: str) -> None:
    await create_stream()
    redis = get_redis_client()
    try:
        message_id = await redis.xadd(
            TRANSCRIPT_STREAM,
            {
                "caller_number": caller_number,
                "speaker": "caller",
                "text": transcription,
                "timestamp": time.time(),
            },
        )
        await redis.publish(
            TRANSCRIPT_CHANNEL,
            json.dumps(
                {
                    "type": "transcript",
                    "message_id": message_id,
                    "caller_number": caller_number,
                    "speaker": "caller",
                    "text": transcription,
                }
            ),
        )
        print(f"Twilio transcript published {message_id}: {transcription}", flush=True)
    finally:
        await redis.aclose()


async def _transcribe_audio_chunk(mulaw_payloads: list[str]) -> str:
    if not mulaw_payloads:
        return ""

    mulaw_audio = b"".join(base64.b64decode(payload) for payload in mulaw_payloads)
    pcm_audio = _mulaw_to_pcm(mulaw_audio)

    # Skip near-silent audio so Whisper never hallucinates filler over it.
    if _pcm_rms(pcm_audio) < SILENCE_RMS_THRESHOLD:
        return ""

    wav_path = ""
    try:
        wav_path = _write_wav_file(pcm_audio)
        transcription = await _transcribe_wav_file(wav_path)
        if transcription:
            print(f"Twilio transcription: {transcription}", flush=True)
        return transcription
    except Exception as error:
        print(f"Twilio transcription error: {error}", flush=True)
        return ""
    finally:
        if wav_path:
            try:
                os.unlink(wav_path)
            except FileNotFoundError:
                pass


def _pcm_rms(pcm_audio: bytes) -> float:
    if not pcm_audio:
        return 0.0

    usable = len(pcm_audio) - (len(pcm_audio) % PCM_SAMPLE_WIDTH)
    if usable <= 0:
        return 0.0

    samples = array.array("h")
    samples.frombytes(pcm_audio[:usable])
    if not samples:
        return 0.0

    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _normalize_for_noise(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _has_scam_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in SCAM_TRANSCRIPT_KEYWORDS)


def _is_probably_noise(text: str) -> bool:
    if _has_scam_keyword(text):
        return False

    normalized = _normalize_for_noise(text)
    if not normalized:
        return True

    if normalized in WHISPER_HALLUCINATIONS:
        return True

    # A lone short token after silence is almost always a hallucination rather
    # than a real utterance worth surfacing.
    words = normalized.split()
    if len(words) <= 1 and len(normalized) <= 4:
        return True

    return False


def _should_publish_transcription(text: str) -> bool:
    normalized = text.strip().lower()
    if len(normalized.split()) >= MIN_TRANSCRIPT_WORDS:
        return True

    return _has_scam_keyword(normalized)


async def _transcription_worker(
    audio_queue: asyncio.Queue[list[str] | None],
    caller_state: dict[str, str],
) -> None:
    pending_text = ""
    pending_cycles = 0

    while True:
        mulaw_payloads = await audio_queue.get()
        if mulaw_payloads is None:
            break

        transcription = await _transcribe_audio_chunk(mulaw_payloads)
        if not transcription:
            continue

        # Drop obvious Whisper silence/hallucination artifacts before they can
        # accumulate into the pending buffer.
        if not pending_text and _is_probably_noise(transcription):
            continue

        pending_text = f"{pending_text} {transcription}".strip()
        pending_cycles += 1

        # Publish as soon as the fragment is meaningful, or once it has waited
        # long enough, so the transcript stays close to real time instead of
        # buffering several utterances together.
        if (
            _should_publish_transcription(pending_text)
            or pending_cycles > MAX_PENDING_FLUSH_CYCLES
        ):
            if _is_probably_noise(pending_text):
                pending_text = ""
                pending_cycles = 0
                continue

            await _write_transcript(pending_text, caller_state["number"])
            pending_text = ""
            pending_cycles = 0

    if pending_text and not _is_probably_noise(pending_text):
        await _write_transcript(pending_text, caller_state["number"])


def _caller_number_from_start(message: dict[str, object]) -> str:
    start = message.get("start")
    if not isinstance(start, dict):
        return "unknown"

    custom_parameters = start.get("customParameters")
    if isinstance(custom_parameters, dict):
        caller_number = custom_parameters.get("caller_number")
        if caller_number:
            return str(caller_number)

    caller_number = start.get("from") or start.get("caller_number")
    return str(caller_number) if caller_number else "unknown"


async def handle_twilio_media(websocket: WebSocket) -> None:
    await websocket.accept()
    print("Twilio media WebSocket connected", flush=True)

    caller_state = {"number": "unknown"}
    audio_buffer: list[str] = []
    audio_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
    transcription_task = asyncio.create_task(
        _transcription_worker(audio_queue, caller_state)
    )
    last_flush = time.monotonic()

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                print("Twilio media event: invalid_json", flush=True)
                continue

            event_type = message.get("event", "unknown")
            print(f"Twilio media event: {event_type}", flush=True)

            if event_type == "start":
                caller_state["number"] = _caller_number_from_start(message)

            if event_type == "media":
                media = message.get("media", {})
                if isinstance(media, dict):
                    payload = media.get("payload")
                    if payload:
                        audio_buffer.append(str(payload))

                now = time.monotonic()
                if now - last_flush >= AUDIO_FLUSH_SECONDS and audio_buffer:
                    buffered_payloads = audio_buffer
                    audio_buffer = []
                    last_flush = now
                    await audio_queue.put(buffered_payloads)

            if event_type == "stop":
                if audio_buffer:
                    await audio_queue.put(audio_buffer)
                    audio_buffer = []
                break
    except WebSocketDisconnect:
        print("Twilio media WebSocket disconnected", flush=True)
    finally:
        if audio_buffer:
            await audio_queue.put(audio_buffer)
        await audio_queue.put(None)
        await transcription_task
