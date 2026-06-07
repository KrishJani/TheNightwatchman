import asyncio
import sys
from pathlib import Path

import weave
from dotenv import load_dotenv
from weave import Evaluation, Scorer


GUARDIAN_DIR = Path(__file__).resolve().parent.parent / "guardian"
sys.path.insert(0, str(GUARDIAN_DIR))

load_dotenv(GUARDIAN_DIR / ".env")

from agents.sentinel import (  # noqa: E402
    _apply_payment_overrides,
    _classify_utterance,
    _fallback_classification,
)


LABELED_UTTERANCES = [
    {
        "text": "You need to buy $500 in Google Play cards right now",
        "expected": "GIFT_CARD_REQUEST",
    },
    {
        "text": "This is Officer Davis, your grandson has been arrested",
        "expected": "AUTHORITY_IMPERSONATION",
    },
    {
        "text": "Do not tell anyone about this call, especially your family",
        "expected": "SECRECY",
    },
    {
        "text": "Your account will be frozen in the next 30 minutes",
        "expected": "URGENCY",
    },
    {
        "text": "Wire the bail money or he stays in jail tonight",
        "expected": "WIRE_REQUEST",
    },
    {"text": "How is the weather today?", "expected": "NONE"},
    {
        "text": "I am calling about your prescription refill",
        "expected": "NONE",
    },
    {"text": "Can we reschedule our lunch?", "expected": "NONE"},
    {"text": "Your package has been delivered", "expected": "NONE"},
    {"text": "Happy birthday, hope you have a great day", "expected": "NONE"},
]


class TacticAccuracyScorer(Scorer):
    @weave.op()
    def score(self, *, output: dict, expected: str) -> dict:
        predicted = output.get("tactic", "NONE")
        return {
            "correct": expected == predicted,
            "expected": expected,
            "predicted": predicted,
        }


@weave.op()
async def classify_tactic(text: str) -> dict[str, str]:
    message = {"text": text, "speaker": "caller"}
    try:
        classification = await _classify_utterance(message)
    except Exception:
        classification = _fallback_classification(message)
    return _apply_payment_overrides(message, classification)


async def main() -> None:
    evaluation = Evaluation(
        dataset=LABELED_UTTERANCES,
        scorers=[TacticAccuracyScorer()],
    )
    summary = await evaluation.evaluate(classify_tactic)

    scorer_summary = summary.get("TacticAccuracyScorer", {})
    correct_stats = scorer_summary.get("correct", {})
    accuracy = correct_stats.get("true_fraction", 0.0)
    correct_count = correct_stats.get("true_count", 0)
    total = len(LABELED_UTTERANCES)

    print(f"Accuracy: {accuracy:.1%} ({correct_count}/{total})")


if __name__ == "__main__":
    asyncio.run(main())
