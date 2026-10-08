"""PC의 실제 JS와 모바일이 공유하는 합성 표시 분할 사례."""

import json
from pathlib import Path

from tests.test_chat_ui_assets import _run_message_helpers_runtime_case


def test_shared_segmentation_uses_real_desktop_helper():
    path = Path(__file__).parents[1] / "contracts/companion/v1/chat_display_split_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    result = _run_message_helpers_runtime_case("""
        let messageSplitEnabled = false;
        const MESSAGE_VISUAL_SENTENCE_SPLIT_MIN_LENGTH = 72;
        const cases = """ + json.dumps(cases) + """;
        result = cases.map(item => {
            messageSplitEnabled = item.enabled;
            return splitMessageIntoVisualChunks(item.text);
        });
    """)
    assert result == [item["expected"] for item in cases]


def test_maximum_public_text_finishes_without_losing_segments():
    result = _run_message_helpers_runtime_case("""
        let messageSplitEnabled = true;
        const MESSAGE_VISUAL_SENTENCE_SPLIT_MIN_LENGTH = 72;
        const long = 'x'.repeat(1048576);
        const lines = 'x\\n'.repeat(524288);
        result = {
            longLength: splitMessageIntoVisualChunks(long)[0].length,
            lineCount: splitMessageIntoVisualChunks(lines).length
        };
    """)
    assert result == {"longLength": 1048576, "lineCount": 524288}
