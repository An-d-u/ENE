"""실제 설치 패키지와 첨부·SDK의 경계 계약을 유료 API 호출 없이 확인한다."""

from __future__ import annotations

import base64
from importlib.metadata import version
import io
from pathlib import Path

from google.genai import _transformers, types
from packaging.requirements import Requirement
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)
import pytest

from src.core.chat_attachments import prepare_attachments
from tests.gemini_structured_fixtures import valid_envelope_json


_REQUIREMENTS = [
    Requirement(line)
    for raw in (Path(__file__).parents[1] / "requirements.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    if (line := raw.split("#", 1)[0].strip())
]


@pytest.mark.parametrize("requirement", _REQUIREMENTS, ids=lambda item: item.name)
def test_installed_runtime_satisfies_declared_requirement(requirement):
    if requirement.marker is not None and not requirement.marker.evaluate():
        pytest.skip("현재 플랫폼에 적용되지 않는 의존성입니다.")
    installed = version(requirement.name)
    assert requirement.specifier.contains(installed), (
        f"설치 환경 불일치: {requirement.name} {installed}, 선언 {requirement}"
    )


def test_gemini_length_retry_config_is_accepted_by_installed_sdk(gemini_harness):
    client = gemini_harness.client([
        gemini_harness.response('{"reply":"합성 미완성', finish_reason="MAX_TOKENS"),
        valid_envelope_json(reply="합성 검증 응답"),
    ], max_tokens=1024)
    client.model_name = "gemini-3-flash-preview"

    assert client.send_message("합성 자료를 설명하세요.")[0] == "합성 검증 응답"

    retry_config = gemini_harness.sdk.send_message_configs[-1]
    parsed = types.GenerateContentConfig.model_validate(retry_config)
    assert parsed.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert parsed.max_output_tokens == 8192
    assert len(gemini_harness.sdk.send_message_configs) == 2


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "JPEG2000"])
def test_image_attachment_and_sdk_conversion_use_installed_codecs(image_format):
    # 외부 파일 대신 정상적인 작은 이미지를 생성해 실제 디코더를 거친다.
    payload = io.BytesIO()
    Image.new("RGB", (12, 8), color="navy").save(payload, format=image_format)
    encoded = base64.b64encode(payload.getvalue()).decode("ascii")
    prepared = prepare_attachments([{
        "name": "synthetic-image.bin",
        "type": "image/png",
        "dataUrl": f"data:image/png;base64,{encoded}",
    }])
    assert prepared[0]["width"] == 12
    assert prepared[0]["height"] == 8
    assert prepared[0]["status"] == "ready"

    with Image.open(io.BytesIO(payload.getvalue())) as image:
        blob = _transformers.pil_to_blob(image)
    assert blob.mime_type == "image/png"
    with Image.open(io.BytesIO(blob.data)) as converted:
        converted.load()
        assert converted.size == (12, 8)
        assert converted.format == "PNG"


def test_pdf_attachment_extracts_text_with_installed_reader():
    # 폰트와 텍스트 스트림을 직접 만든 정상 PDF만 사용한다.
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (Synthetic document) Tj ET")
    page[NameObject("/Contents")] = stream
    payload = io.BytesIO()
    writer.write(payload)
    encoded = base64.b64encode(payload.getvalue()).decode("ascii")

    prepared = prepare_attachments([{
        "name": "synthetic.pdf",
        "type": "application/pdf",
        "dataUrl": f"data:application/pdf;base64,{encoded}",
    }])

    assert prepared[0]["status"] == "ready"
    assert "Synthetic document" in prepared[0]["extractedText"]
