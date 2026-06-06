import asyncio
import time

from redis_client import TRANSCRIPT_STREAM, create_stream, get_redis_client


SIMULATED_CALLER_NUMBER = "14155551234"
SAMPLE_SCRIPT = [
    "This is Officer Daniel Harris with the county police department. I'm calling about your grandson, Michael.",
    "Michael? Is he okay? What happened?",
    "He was in a car accident this morning and was taken into custody. He asked us to call you before anyone else.",
    "Oh my God. Is he hurt?",
    "He's shaken up, but the bigger issue is the judge set emergency bail at $4,800. If it's not posted today, he'll spend the weekend in jail.",
    "I don't understand. Why wouldn't his parents know about this?",
    "Michael begged us not to tell them yet. He said they'd be furious, and he trusts you to help quietly.",
    "How do I pay bail? Can I use my bank card?",
    "The courthouse system is down, so they are accepting Apple gift cards for the bond clerk. Buy them in $500 amounts and read me the numbers.",
    "That sounds unusual. I need to call Michael or his mother first.",
]


async def simulate_call(script: list[str]) -> None:
    await create_stream()

    redis = get_redis_client()
    try:
        for index, utterance in enumerate(script):
            await redis.xadd(
                TRANSCRIPT_STREAM,
                {
                    "caller_number": SIMULATED_CALLER_NUMBER,
                    "speaker": "caller" if index % 2 == 0 else "victim",
                    "text": utterance,
                    "timestamp": time.time(),
                },
            )
            await asyncio.sleep(1.5)
    finally:
        await redis.aclose()
