"""동봉 PixiJS의 실제 버퍼를 합성 도형으로 검사한다. Core·모델·개인 자료는 제공하지 않는다."""

import argparse
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from tools.export_companion_character import RUNTIME


ROOT = Path(__file__).resolve().parents[1]
ROUTES = {
    "/probe.html": ROOT / "tests/companion_character_viewport_probe.html",
    "/probe.js": ROOT / "tests/companion_character_viewport_probe.js",
    "/style.css": ROOT / "assets/web/character/style.css",
    **{f"/{name}": ROOT / "assets/web" / name for name in RUNTIME},
    **{f"/lib/{name}": ROOT / "assets/web/lib" / name
       for name in ("pixi.min.js", "pixi-unsafe-eval.min.js")},
}


class ProbeError(ValueError):
    """검사 실패. 외부 오류 원문을 공개 결과에 포함하지 않는다."""


class ProbeUnavailable(ProbeError):
    """검사를 실행할 환경이 없으며 통과를 뜻하지 않는다."""


class _ResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.count = 0
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre" and dict(attrs).get("id") == "probe-result":
            self.count += 1
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def parse_probe_result(html: str) -> dict:
    parser = _ResultParser()
    parser.feed(html)
    if parser.count != 1 or parser.inside:
        raise ProbeError("완료된 렌더러 검사 결과가 없습니다.")
    try:
        value = json.loads("".join(parser.parts))
    except ValueError as exc:
        raise ProbeError("렌더러 검사 결과를 읽을 수 없습니다.") from exc
    if not isinstance(value, dict):
        raise ProbeError("렌더러 검사 결과 형식이 올바르지 않습니다.")
    if value.get("status") == "unavailable" and value.get("code") == "webgl_unavailable":
        raise ProbeUnavailable("이 브라우저에서 WebGL을 사용할 수 없습니다.")
    fields = ("dpr", "logicalWidth", "logicalHeight", "resolution", "bufferWidth", "bufferHeight",
              "drawingBufferWidth", "drawingBufferHeight", "cssWidth", "cssHeight", "maxWidth", "maxHeight",
              "initialWidth", "initialHeight", "resizeCount", "glError")
    if value.get("status") != "passed" or any(
        type(value.get(key)) not in (int, float) or not math.isfinite(value[key]) for key in fields
    ):
        raise ProbeError("렌더러 검사가 실패했거나 필수 측정값이 없습니다.")
    w, h, r = value["logicalWidth"], value["logicalHeight"], value["resolution"]
    bw, bh = value["bufferWidth"], value["bufferHeight"]
    if not (w > 0 and h > 0 and value["dpr"] > 0 and 0 < r <= 3
            and 1 <= bw <= value["maxWidth"] <= 4096 and 1 <= bh <= value["maxHeight"] <= 4096
            and bw * bh <= 4194304 and bw == math.floor(w * r + .5) and bh == math.floor(h * r + .5)
            and bw == value["drawingBufferWidth"] and bh == value["drawingBufferHeight"]
            and abs(value["cssWidth"] - w) <= .5 / r + .02 and abs(value["cssHeight"] - h) <= .5 / r + .02
            and value["initialWidth"] == value["initialHeight"] == value["resizeCount"] == 1
            and value["glError"] == 0):
        raise ProbeError("렌더러 버퍼·좌표·수명 측정값이 요구 조건과 다릅니다.")
    return value


def resolve_probe_route(path: str) -> Path | None:
    target = ROUTES.get(path)
    if target is None or target.is_symlink() or not target.resolve().is_relative_to(ROOT):
        return None
    return target


class _ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        target = resolve_probe_route(self.path)
        if target is None or not target.is_file():
            self.send_error(404)
            return
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[target.suffix] + "; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_args):
        pass


def run_browser(command: list[str]) -> str:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        stdout, _stderr = process.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        # 이 검사에서 만든 프로세스 트리만 종료한다. 사용자의 브라우저에는 접근하지 않는다.
        if os.name == "nt" and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
        raise
    if process.returncode:
        raise ProbeError("검사용 브라우저 프로세스가 실패했습니다.")
    return stdout


def run_probe(browser: Path, dpr: float) -> dict:
    if not browser.is_file():
        raise ProbeUnavailable("지정한 검사용 브라우저가 없습니다.")
    if not math.isfinite(dpr) or not 1 <= dpr <= 3:
        raise ProbeError("검사용 화면 밀도는 1~3이어야 합니다.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="ene-viewport-probe-") as profile:
            command = [str(browser.resolve()), "--headless=new", "--dump-dom", "--window-size=800,600",
                       f"--force-device-scale-factor={dpr:g}", "--virtual-time-budget=5000",
                       "--disable-background-networking", "--disable-component-update", "--disable-sync",
                       "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}",
                       f"http://127.0.0.1:{server.server_port}/probe.html"]
            try:
                result = parse_probe_result(run_browser(command))
            except subprocess.TimeoutExpired as exc:
                raise ProbeError("검사용 브라우저의 제한 시간을 초과했습니다.") from exc
            if abs(result["dpr"] - dpr) > .001:
                raise ProbeError("요청한 화면 밀도가 실제 브라우저에 적용되지 않았습니다.")
            return result
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", required=True, type=Path, help="이미 설치한 Chrome 또는 Edge 실행 파일")
    args = parser.parse_args()
    try:
        for density in (1, 3, 1.25):
            print(json.dumps(run_probe(args.browser, density), ensure_ascii=False))
    except ProbeUnavailable as exc:
        print(str(exc))
        return 2
    except (ProbeError, OSError) as exc:
        print(str(exc) if isinstance(exc, ProbeError) else "검사용 실행 환경에 접근하지 못했습니다.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
