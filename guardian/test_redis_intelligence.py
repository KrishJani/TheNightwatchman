import unittest

from redis_intelligence import build_redis_intelligence_snapshot


class FakeTimeSeries:
    def __init__(self, points):
        self.points = points

    async def revrange(self, key, start, end, count):
        return list(reversed(self.points))[:count]


class FakeRedis:
    def __init__(self):
        self.timeline = [
            (1717770000000, 0.2),
            (1717770001000, 0.8),
        ]
        self.stream_entries = [
            (
                "1717770000000-0",
                {"text": "hello", "timestamp": "1717770000.0"},
            ),
            (
                "1717770001000-0",
                {"text": "buy gift cards", "timestamp": "1717770001.0"},
            ),
        ]
        self.tactic_hash = {
            "tactic": "GIFT_CARD_REQUEST",
            "confidence": "0.93",
            "playbook_match": "grandparent scam",
        }

    def ts(self):
        return FakeTimeSeries(self.timeline)

    async def xrange(self, key, min="-", max="+", count=None):
        return self.stream_entries[:count] if count else self.stream_entries

    async def xrevrange(self, key, max="+", min="-", count=None):
        entries = list(reversed(self.stream_entries))
        return entries[:count] if count else entries

    async def xlen(self, key):
        return len(self.stream_entries)

    async def hgetall(self, key):
        if key == "guardian:tactic:1717770001000-0":
            return self.tactic_hash
        return {}


class RedisIntelligenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_builds_snapshot_with_live_redis_fields(self):
        snapshot = await build_redis_intelligence_snapshot(
            FakeRedis(),
            now_ms=1717770003500,
        )

        self.assertEqual(
            snapshot["timeseries"]["points"],
            [
                {"timestamp": 1717770000000, "score": 0.2},
                {"timestamp": 1717770001000, "score": 0.8},
            ],
        )
        self.assertEqual(snapshot["hashes"]["last_message_id"], "1717770001000-0")
        self.assertEqual(snapshot["hashes"]["tactic"], "GIFT_CARD_REQUEST")
        self.assertEqual(snapshot["hashes"]["confidence"], 0.93)
        self.assertEqual(snapshot["streams"]["total_messages"], 2)
        self.assertEqual(snapshot["streams"]["last_entry_ms_ago"], 2500)


if __name__ == "__main__":
    unittest.main()
