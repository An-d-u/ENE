"""
기존 수동 실행 진입점 호환용 파일.
실제 테스트는 pytest 기반 tests/ 아래로 이관됨.
"""
import sys

import pytest


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", "tests/test_memory_manager.py", "tests/test_memory_types.py"]))
