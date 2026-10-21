# Synthetic voice fixture

`voice-greeting.wav` is the existing Lobuddy P8 test synthesis of “你好，請只回答我在。” using the selected Fish voice and free API tier. It contains no microphone recording or user conversation. The generation logic was `scripts/voice_smoke.py` at the pre-TS baseline; the observed P8 measurements are retained in `reports/2026-10-16_p8_voice.md`.

Keep this fixed 16 kHz, mono PCM16 fixture for comparable native audio lifecycle checks. A passing synthetic stream does not establish microphone quality, acoustic echo suppression, physical audibility or conversational naturalness.
