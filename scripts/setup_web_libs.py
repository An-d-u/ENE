"""
ENE 프로젝트 Setup 스크립트 - 수정 버전
Cubism 4만 지원하는 pixi-live2d-display 버전 사용
"""
import os
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def get_project_root() -> Path:
    """스크립트 위치와 무관하게 프로젝트 루트를 반환한다."""
    return Path(__file__).resolve().parents[1]


def check_local_core(project_root: Path) -> bool:
    """사용자가 직접 설치한 Core만 검사하며 다운로드·덮어쓰기는 하지 않는다."""
    core = project_root / "assets/web/lib/live2dcubismcore.min.js"
    try:
        manifest = json.loads((project_root / "contracts/companion/character-runtime.json").read_text(encoding="utf-8"))
        expected = next(item["sha256"] for item in manifest["files"] if item["target"] == "lib/live2dcubismcore.min.js")
        if core.is_file() and hashlib.sha256(core.read_bytes()).hexdigest() == expected:
            print("로컬 Core 해시 검사 통과. 배포 허가를 의미하지 않습니다.")
            return True
    except (OSError, ValueError, KeyError, StopIteration):
        pass
    print("Core가 없거나 지원하는 파일과 다릅니다. 기존 파일은 변경하지 않았습니다.")
    print("https://www.live2d.com/en/sdk/download/web/ 에서 약관을 확인한 뒤 직접 다운로드하세요.")
    print("SDK의 Core/live2dcubismcore.min.js를 assets/web/lib/live2dcubismcore.min.js에 배치하세요.")
    print("지원 해시와 버전 변경 절차: docs/source-only-build.md")
    return False


def download_file(url, save_path):
    """URL에서 파일을 다운로드하여 저장"""
    print(f"Downloading: {url}")
    print(f"Saving to: {save_path}")
    
    try:
        # 디렉토리가 없으면 생성
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # 파일 다운로드
        urllib.request.urlretrieve(url, save_path)
        
        # 파일 크기 확인
        file_size = os.path.getsize(save_path)
        print(f"[OK] Downloaded successfully ({file_size:,} bytes)\n")
        return True
    except Exception as e:
        print(f"[FAIL] Failed to download: {e}\n")
        return False


def setup_libraries():
    """필요한 JavaScript 라이브러리 다운로드"""
    print("=" * 60)
    print("ENE Project - JavaScript Libraries Setup (Cubism 4 only)")
    print("=" * 60)
    print()
    
    # 프로젝트 루트 디렉토리
    base_dir = get_project_root()
    lib_dir = base_dir / "assets" / "web" / "lib"
    
    # 다운로드할 라이브러리 목록 - jsdelivr를 통해 정확한 파일 가져오기
    libraries = [
        {
            "name": "Pixi.js v7.3.0",
            "url": "https://cdn.jsdelivr.net/npm/pixi.js@7.3.0/dist/pixi.min.js",
            "filename": "pixi.min.js"
        },
        {
            "name": "pixi-live2d-display (cubism4 build)",
            "url": "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
            "filename": "pixi-live2d-display.min.js"
        }
    ]
    
    success_count = 0
    
    for lib in libraries:
        print(f"[{libraries.index(lib) + 1}/{len(libraries)}] {lib['name']}")
        save_path = lib_dir / lib['filename']
        
        if download_file(lib['url'], str(save_path)):
            success_count += 1
    
    print("=" * 60)
    print(f"Setup Complete: {success_count}/{len(libraries)} libraries downloaded")
    print("=" * 60)
    
    if success_count == len(libraries):
        print("\n[OK] All libraries downloaded successfully!")
        print("  You can now run the application with: python main.py")
        return check_local_core(base_dir)
    else:
        print("\n[FAIL] Some libraries failed to download.")
        print("  Please check your internet connection and try again.")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-core", action="store_true", help="다운로드 없이 로컬 Core만 검사")
    args = parser.parse_args()
    raise SystemExit(0 if (check_local_core(get_project_root()) if args.check_core else setup_libraries()) else 1)
