"""실제 Pixi 초기화와 모바일 CSP 경계를 함께 검사한다."""

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_real_pixi_initializes_without_javascript_eval():
    result = subprocess.run(
        ["node", str(ROOT / "tests/companion_pixi_csp_harness.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_mobile_csp_keeps_eval_blocked_and_loads_compatibility_first():
    html = (ROOT / "assets/web/character/index.html").read_text(encoding="utf-8")
    assert "'unsafe-eval'" not in html
    assert "script-src 'self' 'wasm-unsafe-eval'" in html
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert scripts[:4] == [
        "lib/pixi.min.js", "lib/pixi-unsafe-eval.min.js",
        "lib/live2dcubismcore.min.js", "lib/pixi-live2d-display.min.js",
    ]
