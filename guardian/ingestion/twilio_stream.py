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
from twilio.rest import Client
from twilio.twiml.voice_response import Start, VoiceResponse

from redis_client import (
    TRANSCRIPT_CHANNEL,
    TRANSCRIPT_STREAM,
    create_stream,
    get_redis_client,
    matches_recent_victim_transcript,
)

try:
    import audioop
except ModuleNotFoundError:
    audioop = None


load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
TARGET_PHONE_NUMBER = os.getenv("TARGET_PHONE_NUMBER", "")
WHISPER_MODEL = "whisper-1"
# The caller's speech is segmented on natural pauses rather than a fixed clock,
# so each Whisper request receives one complete utterance instead of a slice cut
# mid-word. This is what keeps the transcript both full and close to real time.
SILENCE_HANG_SECONDS = 0.8  # silence after speech that ends an utterance
MAX_UTTERANCE_SECONDS = 15  # safety flush for a caller who never pauses
# When the caller has not started speaking yet, keep only a short lead-in of
# buffered frames so a long quiet stretch never balloons the buffer.
PRE_SPEECH_LEAD_SECONDS = 0.4
MULAW_SAMPLE_RATE = 8000
PCM_SAMPLE_WIDTH = 2
# Each Twilio media frame carries 20 ms of 8 kHz mulaw audio.
MULAW_FRAME_SECONDS = 0.02
PRE_SPEECH_LEAD_FRAMES = int(PRE_SPEECH_LEAD_SECONDS / MULAW_FRAME_SECONDS)
# Per-frame RMS (after mulaw->PCM) above which a frame counts as speech.
SPEECH_RMS_THRESHOLD = 300
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


def is_twilio_configured() -> bool:
    return bool(TWILIO_PHONE_NUMBER.strip())


def _get_ngrok_host() -> str:
    load_dotenv(override=True)
    configured_ngrok_url = os.getenv("NGROK_URL", "")
    ngrok_url = configured_ngrok_url.strip().rstrip("/")
    if not ngrok_url:
        raise ValueError("Set NGROK_URL to your bare ngrok domain")

    parsed = urlparse(ngrok_url)
    host = parsed.netloc or parsed.path
    if not host:
        raise ValueError(f"Invalid NGROK_URL: {configured_ngrok_url}")

    return host


def _get_twilio_webhook_base() -> str:
    return f"https://{_get_ngrok_host()}"


def _get_media_ws_url() -> str:
    return f"wss://{_get_ngrok_host()}/twilio/media"


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


async def start_twilio_outbound_call() -> dict[str, str]:
    load_dotenv(override=True)

    if not is_twilio_configured():
        raise ValueError("TWILIO_PHONE_NUMBER is not set")

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = TWILIO_PHONE_NUMBER.strip()
    to_number = os.getenv("TARGET_PHONE_NUMBER", "").strip()

    missing = [
        name
        for name, value in [
            ("TWILIO_ACCOUNT_SID", account_sid),
            ("TWILIO_AUTH_TOKEN", auth_token),
            ("TARGET_PHONE_NUMBER", to_number),
            ("NGROK_URL", os.getenv("NGROK_URL", "").strip()),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required Twilio settings: {', '.join(missing)}")

    twiml_url = f"{_get_twilio_webhook_base()}/twilio/incoming"
    client = Client(account_sid, auth_token)

    def _create_call() -> object:
        return client.calls.create(
            to=to_number,
            from_=from_number,
            url=twiml_url,
        )

    call = await asyncio.to_thread(_create_call)
    print(
        f"Twilio outbound call started {call.sid}: {from_number} -> {to_number}",
        flush=True,
    )
    return {
        "status": "calling",
        "call_sid": str(call.sid),
        "to": to_number,
        "from": from_number,
    }


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


def _mulaw_payload_rms(payload: str) -> float:
    """RMS amplitude of a single base64 mulaw media frame, used for VAD."""
    try:
        mulaw_audio = base64.b64decode(payload)
    except (ValueError, TypeError):
        return 0.0

    if not mulaw_audio:
        return 0.0

    return _pcm_rms(_mulaw_to_pcm(mulaw_audio))


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


async def _transcription_worker(
    audio_queue: asyncio.Queue[list[str] | None],
    caller_state: dict[str, str],
) -> None:
    # Each queued item is one complete utterance (segmented on a pause), so it
    # can be transcribed and published as a single full sentence.
    while True:
        mulaw_payloads = await audio_queue.get()
        if mulaw_payloads is None:
            break

        transcription = await _transcribe_audio_chunk(mulaw_payloads)
        if not transcription:
            continue

        if _is_probably_noise(transcription):
            continue

        if await matches_recent_victim_transcript(transcription):
            print(
                f"Skipping Twilio transcript (matches victim mic): {transcription}",
                flush=True,
            )
            continue

        await _write_transcript(transcription, caller_state["number"])


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
    # Voice-activity state for utterance segmentation.
    has_speech = False
    last_voice_at = time.monotonic()
    utterance_started_at = time.monotonic()

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
                payload = media.get("payload") if isinstance(media, dict) else None
                if not payload:
                    continue

                payload = str(payload)
                audio_buffer.append(payload)
                now = time.monotonic()

                if _mulaw_payload_rms(payload) >= SPEECH_RMS_THRESHOLD:
                    if not has_speech:
                        utterance_started_at = now
                    has_speech = True
                    last_voice_at = now

                if not has_speech:
                    # Keep only a short lead-in so silence never accumulates.
                    if len(audio_buffer) > PRE_SPEECH_LEAD_FRAMES:
                        audio_buffer = audio_buffer[-PRE_SPEECH_LEAD_FRAMES:]
                    continue

                ended_on_pause = now - last_voice_at >= SILENCE_HANG_SECONDS
                ended_on_max_length = now - utterance_started_at >= MAX_UTTERANCE_SECONDS
                if ended_on_pause or ended_on_max_length:
                    await audio_queue.put(audio_buffer)
                    audio_buffer = []
                    has_speech = False

            if event_type == "stop":
                if has_speech and audio_buffer:
                    await audio_queue.put(audio_buffer)
                    audio_buffer = []
                break
    except WebSocketDisconnect:
        print("Twilio media WebSocket disconnected", flush=True)
    finally:
        if has_speech and audio_buffer:
            await audio_queue.put(audio_buffer)
        await audio_queue.put(None)
        await transcription_task
