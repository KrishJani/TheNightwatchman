import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import weave
from dotenv import load_dotenv
from openai import AsyncOpenAI
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from redis_client import (
    ALERTS_CHANNEL,
    COACHING_CHANNEL,
    TRANSCRIPT_STREAM,
    cleanup_call_data,
    get_redis_client,
)


MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
RISK_THRESHOLD = 0.6
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
INCIDENT_REPORT_PROMPT = (
    "You are writing a formal scam incident report. Given this call log, produce a "
    "clear report with exactly these section headers on their own lines: "
    "Summary, Tactics Used, Key Moments, Recommended Actions. "
    "Use plain text only. Do not use markdown, asterisks, hashtags, or bullet symbols. "
    "Keep it under 300 words. Be factual and calm."
)
REPORT_SECTIONS = ("Summary", "Tactics Used", "Key Moments", "Recommended Actions")


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


@dataclass
class IncidentLog:
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_risk_score: float = 0.0

    def record_alert(self, alert: dict[str, Any]) -> None:
        message_id = str(alert.get("message_id", ""))
        if not message_id:
            return

        risk_score = float(alert.get("score", 0))
        self.max_risk_score = max(self.max_risk_score, risk_score)

        entry = self.entries.setdefault(
            message_id,
            {
                "message_id": message_id,
                "text": alert.get("text", ""),
                "tactic": alert.get("tactic", "NONE"),
                "risk_score": risk_score,
                "timestamp": time.time(),
                "risk_timestamp_ms": int(time.time() * 1000),
                "playbook_match": alert.get("playbook_match"),
                "coaching_tips": [],
            },
        )
        entry["text"] = alert.get("text", entry["text"])
        entry["tactic"] = alert.get("tactic", entry["tactic"])
        entry["risk_score"] = risk_score
        if alert.get("playbook_match"):
            entry["playbook_match"] = alert["playbook_match"]

    def record_coaching_tip(self, payload: dict[str, Any]) -> None:
        message_id = str(payload.get("message_id", ""))
        tip = payload.get("tip", "")
        if not message_id or not tip:
            return

        entry = self.entries.setdefault(
            message_id,
            {
                "message_id": message_id,
                "text": "",
                "tactic": payload.get("tactic", "UNKNOWN"),
                "risk_score": 0.0,
                "timestamp": time.time(),
                "risk_timestamp_ms": int(time.time() * 1000),
                "playbook_match": None,
                "coaching_tips": [],
            },
        )
        if tip not in entry["coaching_tips"]:
            entry["coaching_tips"].append(tip)

    def ordered_entries(self) -> list[dict[str, Any]]:
        return sorted(self.entries.values(), key=lambda entry: entry["timestamp"])

    def reset(self) -> None:
        self.entries.clear()
        self.max_risk_score = 0.0


incident_log = IncidentLog()


def _get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.getenv("WANDB_API_KEY"),
        base_url=INFERENCE_BASE_URL,
    )


def _format_call_log(entries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for entry in entries:
        timestamp = time.strftime(
            "%H:%M:%S",
            time.localtime(entry["timestamp"]),
        )
        line = (
            f"[{timestamp}] Tactic: {entry['tactic']} | Risk: {entry['risk_score']:.2f} | "
            f"Utterance: {entry['text']}"
        )
        if entry.get("playbook_match"):
            line += f" | Playbook match: {entry['playbook_match']}"
        if entry.get("coaching_tips"):
            line += f" | Coaching tips: {'; '.join(entry['coaching_tips'])}"
        lines.append(line)
    return "\n".join(lines)


@weave.op()
async def _generate_incident_report(call_log: str) -> str:
    client = _get_llm_client()
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": INCIDENT_REPORT_PROMPT},
            {"role": "user", "content": call_log},
        ],
        temperature=0.2,
        max_tokens=500,
    )
    return (response.choices[0].message.content or "").strip()


def _strip_markdown(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[-*]\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
    cleaned = re.sub(r"^>\s*", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def _parse_report_sections(report_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_header: str | None = None
    buffer: list[str] = []

    for line in report_text.splitlines():
        normalized = _strip_markdown(line).strip().rstrip(":")
        if normalized in REPORT_SECTIONS:
            if current_header and buffer:
                sections[current_header] = _strip_markdown("\n".join(buffer))
            current_header = normalized
            buffer = []
        elif current_header:
            buffer.append(line)

    if current_header and buffer:
        sections[current_header] = _strip_markdown("\n".join(buffer))

    if not sections:
        sections["Summary"] = _strip_markdown(report_text)

    return sections


def _fallback_report_sections(
    entries: list[dict[str, Any]],
    call_log: str,
) -> dict[str, str]:
    tactics = sorted({entry["tactic"] for entry in entries if entry["tactic"] != "NONE"})
    return {
        "Summary": (
            "Elevated scam risk was detected during this monitored call. "
            "Guardian flagged multiple manipulation tactics consistent with a confirmed scam attempt."
        ),
        "Tactics Used": ", ".join(tactics) if tactics else "None identified",
        "Key Moments": call_log,
        "Recommended Actions": (
            "Do not send money, gift cards, or wire transfers. "
            "Contact local authorities and verify the caller through an independent phone number. "
            "Preserve this report for your records."
        ),
    }


async def _build_transcript(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entry_by_id = {entry["message_id"]: entry for entry in entries}
    redis = get_redis_client()
    transcript: list[dict[str, Any]] = []

    try:
        for message_id in sorted(
            entry_by_id,
            key=lambda mid: entry_by_id[mid]["timestamp"],
        ):
            entry = entry_by_id[message_id]
            speaker = "unknown"
            text = entry["text"]
            timestamp = entry["timestamp"]

            stream_entries = await redis.xrange(
                TRANSCRIPT_STREAM,
                min=message_id,
                max=message_id,
                count=1,
            )
            if stream_entries:
                _, fields = stream_entries[0]
                speaker = fields.get("speaker", speaker)
                text = fields.get("text", text)
                timestamp = float(fields.get("timestamp", timestamp))

            transcript.append(
                {
                    "speaker": speaker,
                    "text": text,
                    "timestamp": timestamp,
                    "tactic": entry.get("tactic", "NONE"),
                    "risk_score": entry.get("risk_score", 0.0),
                    "playbook_match": entry.get("playbook_match"),
                    "coaching_tips": entry.get("coaching_tips", []),
                }
            )
    finally:
        await redis.aclose()

    return transcript


def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "banner": ParagraphStyle(
            "ReportBanner",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "meta_label": ParagraphStyle(
            "MetaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=colors.HexColor("#475569"),
        ),
        "meta_value": ParagraphStyle(
            "MetaValue",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#0f172a"),
        ),
        "meta_value_alert": ParagraphStyle(
            "MetaValueAlert",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=colors.HexColor("#991b1b"),
        ),
        "section": ParagraphStyle(
            "SectionHeader",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=colors.HexColor("#991b1b"),
            spaceBefore=14,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["BodyText"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=8,
        ),
        "transcript_speaker_caller": ParagraphStyle(
            "CallerSpeaker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.HexColor("#991b1b"),
            spaceBefore=8,
        ),
        "transcript_speaker_victim": ParagraphStyle(
            "VictimSpeaker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.HexColor("#1d4ed8"),
            spaceBefore=8,
        ),
        "transcript_text": ParagraphStyle(
            "TranscriptText",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#0f172a"),
            leftIndent=12,
            spaceAfter=2,
        ),
        "transcript_meta": ParagraphStyle(
            "TranscriptMeta",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#64748b"),
            leftIndent=12,
            spaceAfter=6,
        ),
        "transcript_flag": ParagraphStyle(
            "TranscriptFlag",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#991b1b"),
            leftIndent=12,
            spaceAfter=8,
        ),
        "coaching_note": ParagraphStyle(
            "CoachingNote",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#1d4ed8"),
            leftIndent=12,
            spaceAfter=8,
        ),
    }


def _write_report_pdf(
    report_path: Path,
    sections: dict[str, str],
    transcript: list[dict[str, Any]],
    timestamp: int,
    max_risk: float,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _pdf_styles()
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    doc = SimpleDocTemplate(
        str(report_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    story: list[Any] = [
        Paragraph("GUARDIAN INCIDENT REPORT", styles["title"]),
        Paragraph("Official Scam Call Documentation", styles["subtitle"]),
    ]

    banner = Table(
        [[Paragraph("CONFIRMED SCAM CALL", styles["banner"])]],
        colWidths=[6.5 * inch],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#991b1b")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([banner, Spacer(1, 0.2 * inch)])

    meta_table = Table(
        [
            [
                Paragraph("Report ID", styles["meta_label"]),
                Paragraph(f"guardian_incident_{timestamp}", styles["meta_value"]),
            ],
            [
                Paragraph("Generated", styles["meta_label"]),
                Paragraph(generated_at, styles["meta_value"]),
            ],
            [
                Paragraph("Peak Risk Score", styles["meta_label"]),
                Paragraph(f"{max_risk:.2f}", styles["meta_value_alert"]),
            ],
            [
                Paragraph("Classification", styles["meta_label"]),
                Paragraph("Confirmed Scam", styles["meta_value_alert"]),
            ],
        ],
        colWidths=[1.4 * inch, 5.1 * inch],
        hAlign="LEFT",
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([meta_table, Spacer(1, 0.1 * inch), HRFlowable(width="100%", thickness=1)])

    for section_name in REPORT_SECTIONS:
        body = sections.get(section_name, "").strip()
        if not body:
            continue
        story.append(Paragraph(section_name.upper(), styles["section"]))
        story.append(Paragraph(escape(body).replace("\n", "<br/>"), styles["body"]))

    story.extend(
        [
            HRFlowable(width="100%", thickness=1, spaceBefore=10, spaceAfter=10),
            Paragraph("CALL TRANSCRIPT", styles["section"]),
            Paragraph(
                "Complete conversation as recorded during the monitored call.",
                styles["transcript_meta"],
            ),
        ]
    )

    for turn in transcript:
        speaker = str(turn["speaker"]).lower()
        speaker_label = speaker.upper()
        time_label = time.strftime("%H:%M:%S", time.localtime(turn["timestamp"]))
        speaker_style = (
            styles["transcript_speaker_caller"]
            if speaker == "caller"
            else styles["transcript_speaker_victim"]
        )

        story.append(
            Paragraph(
                f"{speaker_label} <font color='#64748b'>{time_label}</font>",
                speaker_style,
            )
        )
        story.append(
            Paragraph(f'"{escape(turn["text"])}"', styles["transcript_text"]),
        )

        tactic = turn.get("tactic", "NONE")
        if tactic and tactic != "NONE":
            flag_parts = [
                f"Detected tactic: {escape(tactic)}",
                f"Risk score: {turn.get('risk_score', 0.0):.2f}",
            ]
            if turn.get("playbook_match"):
                flag_parts.append(f"Playbook match: {escape(turn['playbook_match'])}")
            story.append(
                Paragraph(" | ".join(flag_parts), styles["transcript_flag"]),
            )

        for tip in turn.get("coaching_tips", []):
            story.append(
                Paragraph(f"Guardian coaching: {escape(tip)}", styles["coaching_note"]),
            )

    doc.build(story)


async def finalize_call() -> dict[str, str]:
    entries = incident_log.ordered_entries()
    max_risk = incident_log.max_risk_score
    message_ids = [entry["message_id"] for entry in entries]
    risk_timestamps_ms = [
        entry["risk_timestamp_ms"]
        for entry in entries
        if entry.get("risk_timestamp_ms") is not None
    ]

    if max_risk > RISK_THRESHOLD:
        call_log = _format_call_log(entries)
        transcript = await _build_transcript(entries)
        try:
            report_text = await _generate_incident_report(call_log)
            sections = _parse_report_sections(report_text)
        except Exception as error:
            print(f"Scribe LLM error: {error}; using fallback report", flush=True)
            sections = _fallback_report_sections(entries, call_log)

        timestamp = int(time.time())
        filename = f"guardian_incident_{timestamp}.pdf"
        report_path = REPORTS_DIR / filename
        _write_report_pdf(report_path, sections, transcript, timestamp, max_risk)
        incident_log.reset()

        print(f"Scribe confirmed scam (max risk {max_risk:.2f}); report saved to {report_path}", flush=True)
        return {
            "status": "scam",
            "timestamp": str(timestamp),
            "message": "Scam confirmed. Download your incident report.",
            "report_filename": filename,
        }

    await cleanup_call_data(message_ids, risk_timestamps_ms)
    incident_log.reset()

    print(f"Scribe cleared clean call (max risk {max_risk:.2f}); Redis data deleted", flush=True)
    return {
        "status": "clean",
        "message": "No scam detected. All data deleted.",
    }


async def scribe_agent() -> None:
    redis = get_redis_client()
    pubsub = redis.pubsub()

    try:
        await pubsub.subscribe(ALERTS_CHANNEL, COACHING_CHANNEL)

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1,
            )
            if message is None or message["type"] != "message":
                continue

            payload = json.loads(message["data"])
            channel = message["channel"]
            if channel == ALERTS_CHANNEL:
                incident_log.record_alert(payload)
            elif channel == COACHING_CHANNEL:
                incident_log.record_coaching_tip(payload)
    finally:
        await pubsub.unsubscribe(ALERTS_CHANNEL, COACHING_CHANNEL)
        await pubsub.aclose()
        await redis.aclose()
