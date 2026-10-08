"""기기 문맥 합성을 중립 입력으로 검증한다."""

import importlib
import importlib.util
import pytest


def helper():
    assert importlib.util.find_spec("src.ai.input_device_context") is not None
    return importlib.import_module(
        "src.ai.input_device_context"
    ).append_input_device_context


@pytest.mark.parametrize("device", [None, "automatic", "unknown", 1, {}, ["pc"]])
def test_invalid_device_is_exact_noop(device):
    assert helper()("가상 선분", device, "ko") == "가상 선분"


@pytest.mark.parametrize(
    "language,label",
    [("ko", "모바일 앱"), ("en", "mobile app"), ("ja", "モバイルアプリ")],
)
def test_localized_transient_context(language, label):
    result = helper()("가상 선분", "mobile", language)
    assert result.startswith("가상 선분\n\n")
    assert result.count("[Input device context]") == 1
    assert label in result
    assert helper()("가상 선분", "pc", language) != result
