"""
ENE 프로젝트 Setup 스크립트 - 수정 버전
Cubism 4만 지원하는 pixi-live2d-display 버전 사용
"""
import os
import urllib.request
from pathlib import Path


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
    base_dir = Path(__file__).parent
    lib_dir = base_dir / "assets" / "web" / "lib"
    
    # 다운로드할 라이브러리 목록 - jsdelivr를 통해 정확한 파일 가져오기
    libraries = [
        {
            "name": "Pixi.js v7.3.0",
            "url": "https://cdn.jsdelivr.net/npm/pixi.js@7.3.0/dist/pixi.min.js",
            "filename": "pixi.min.js"
        },
        {
            "name": "Live2D Cubism Core",
            "url": "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js",
            "filename": "live2dcubismcore.min.js"
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
        return True
    else:
        print("\n[FAIL] Some libraries failed to download.")
        print("  Please check your internet connection and try again.")
        return False


if __name__ == "__main__":
    setup_libraries()
