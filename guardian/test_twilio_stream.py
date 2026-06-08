import base64
import unittest

from ingestion.twilio_stream import (
    SPEECH_RMS_THRESHOLD,
    _mulaw_payload_rms,
)

# One Twilio media frame is 160 mulaw bytes (20 ms at 8 kHz). These byte
# values map through the mulaw decoder to known amplitudes, so the tests do
# not depend on the (removed-in-3.13) audioop encoder.
FRAME_LEN = 160
MULAW_SILENCE = 0xFF  # decodes to ~0
MULAW_NEAR_SILENCE = 0xF0  # decodes to ~120 (quiet background)
MULAW_LOUD = 0x00  # decodes to ~ -32000 (loud speech)


def _frame(byte_value: int) -> str:
    return base64.b64encode(bytes([byte_value]) * FRAME_LEN).decode()


class MulawFrameRmsTests(unittest.TestCase):
    def test_silent_frame_is_below_speech_threshold(self):
        self.assertLess(_mulaw_payload_rms(_frame(MULAW_SILENCE)), SPEECH_RMS_THRESHOLD)

    def test_quiet_background_frame_is_below_threshold(self):
        self.assertLess(
            _mulaw_payload_rms(_frame(MULAW_NEAR_SILENCE)), SPEECH_RMS_THRESHOLD
        )

    def test_loud_speech_frame_is_above_threshold(self):
        self.assertGreater(_mulaw_payload_rms(_frame(MULAW_LOUD)), SPEECH_RMS_THRESHOLD)

    def test_invalid_payload_returns_zero(self):
        self.assertEqual(_mulaw_payload_rms("not base64!!!"), 0.0)


if __name__ == "__main__":
    unittest.main()
