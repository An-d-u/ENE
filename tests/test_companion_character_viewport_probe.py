"""실제 렌더러 검사 도구의 결과·파일 제공 경계만 합성 자료로 검사한다."""

import json
from html import escape
from pathlib import Path
import subprocess

import pytest

from tools import companion_character_viewport_probe as probe


def result_html(**overrides):
    value = {
        "status": "passed", "dpr": 3, "logicalWidth": 400, "logicalHeight": 600,
        "resolution": 3, "bufferWidth": 1200, "bufferHeight": 1800,
        "drawingBufferWidth": 1200, "drawingBufferHeight": 1800,
        "cssWidth": 400, "cssHeight": 600, "maxWidth": 4096, "maxHeight": 4096,
        "initialWidth": 1, "initialHeight": 1, "resizeCount": 1, "glError": 0,
    }
    value.update(overrides)
    return '<pre id="probe-result">' + escape(json.dumps(value)) + '</pre>'


def test_parse_requires_complete_measured_result():
    assert probe.parse_probe_result(result_html())["bufferWidth"] == 1200
    for invalid in ("", '<pre id="probe-result">pending</pre>', result_html() + result_html(),
                    '<pre id="probe-result">{"status":"passed"}</pre>'):
        with pytest.raises(probe.ProbeError):
            probe.parse_probe_result(invalid)


@pytest.mark.parametrize("field,value", [
    ("bufferWidth", 9000), ("drawingBufferWidth", 1199), ("resolution", 0),
    ("cssWidth", 900), ("initialWidth", 800), ("resizeCount", 2), ("glError", 1280),
    ("dpr", float("nan")), ("dpr", "3"), ("dpr", True), ("maxWidth", 1024),
])
def test_parse_rejects_failed_measurements(field, value):
    with pytest.raises(probe.ProbeError):
        probe.parse_probe_result(result_html(**{field: value}))


def test_unavailable_context_is_not_a_passing_result():
    with pytest.raises(probe.ProbeUnavailable):
        probe.parse_probe_result('<pre id="probe-result">{"status":"unavailable","code":"webgl_unavailable"}</pre>')
    with pytest.raises(probe.ProbeError):
        probe.parse_probe_result('<pre id="probe-result">{"status":"failed","code":"buffer_mismatch"}</pre>')


@pytest.mark.parametrize("route", [
    "/config.json", "/models/model.json", "/../config.json", "/%2e%2e/config.json",
    "/probe.js?file=config.json", "/lib/live2dcubismcore.min.js", "/probe.js#part",
    "/runtime_character_host.js/../probe.js", "file:///private", "/C:/private",
])
def test_route_map_never_serves_private_or_unlisted_files(route):
    assert probe.resolve_probe_route(route) is None


def test_route_map_uses_only_existing_bundled_and_synthetic_files():
    routes = ["/probe.html", "/probe.js", "/lib/pixi.min.js", "/lib/pixi-unsafe-eval.min.js",
              "/runtime_character_host.js", "/runtime_character_state.js"]
    for route in routes:
        target = probe.resolve_probe_route(route)
        assert isinstance(target, Path) and target.is_file()
    html = probe.resolve_probe_route("/probe.html").read_text(encoding="utf-8")
    assert "'unsafe-eval'" not in html
    assert "live2dcubismcore" not in html


def test_browser_absence_and_timeout_have_distinct_failures(tmp_path, monkeypatch):
    with pytest.raises(probe.ProbeUnavailable):
        probe.run_probe(tmp_path / "missing-browser", 3)
    browser = tmp_path / "synthetic-browser"
    browser.touch()

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("synthetic", 45)

    monkeypatch.setattr(probe, "run_browser", timeout)
    with pytest.raises(probe.ProbeError, match="시간"):
        probe.run_probe(browser, 3)


def test_browser_arguments_keep_sandbox_and_use_an_isolated_profile(tmp_path, monkeypatch):
    browser = tmp_path / "synthetic-browser"
    browser.touch()
    seen = []

    def capture(command):
        seen.extend(command)
        return result_html()

    monkeypatch.setattr(probe, "run_browser", capture)
    assert probe.run_probe(browser, 3)["dpr"] == 3
    assert "--no-sandbox" not in seen
    assert "--ignore-certificate-errors" not in seen
    assert "--force-device-scale-factor=3" in seen
    assert seen[-1].startswith("http://127.0.0.1:")
    assert any(item.startswith("--user-data-dir=") for item in seen)


def test_requested_density_must_match_actual_browser_density(tmp_path, monkeypatch):
    browser = tmp_path / "synthetic-browser"
    browser.touch()
    monkeypatch.setattr(probe, "run_browser", lambda _command: result_html())
    with pytest.raises(probe.ProbeError, match="밀도"):
        probe.run_probe(browser, 1)
