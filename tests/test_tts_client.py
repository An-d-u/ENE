from src.ai.tts_client import TTSClient


def test_normalize_tts_text_normalizes_newlines_and_blanks():
    raw = "  1행\r\n\r\n\r\n 2행 \r3행\n\n"
    normalized = TTSClient._normalize_tts_text(raw)
    assert normalized == "1행\n\n2행\n3행"