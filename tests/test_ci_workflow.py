"""테스트 실패가 뒤의 커버리지 성공으로 숨겨지지 않는 CI 계약을 확인한다."""

from pathlib import Path
import re


def test_pytest_and_coverage_report_have_independent_failure_steps():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    steps = re.split(r"(?m)^      - name: ", workflow)[1:]
    test_steps = [step for step in steps if "-m coverage run " in step]
    report_steps = [step for step in steps if "-m coverage report " in step]
    assert test_steps and report_steps
    for step in test_steps:
        assert "-m pytest -q" in step
        assert "-m coverage report " not in step
        assert "continue-on-error" not in step
    for step in report_steps:
        assert "--fail-under=80" in step
        assert "continue-on-error" not in step
