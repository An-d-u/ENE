import os
import requests

TARGET_DIR = os.path.join("assets", "web", "libs")

FILES = {
    "live2dCubismCore.min.js": "https://cdn.jsdelivr.net/npm/live2dcubismcore@1.0.2/live2dcubismcore.min.js",
    "pixi.min.js": "https://cdnjs.cloudflare.com/ajax/libs/pixi.js/6.5.8/browser/pixi.min.js",
    "cubism4.min.js": "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
    "qwebchannel.js": "https://github.com/qt/qtwebchannel/blob/dev/src/webchannel/qwebchannel.js"
}

def download_file(url, folder, filename):
    filepath = os.path.join(folder, filename)
    print(f"Downloading {filename}...")
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)
        print(f" -> Success! ({len(response.content)/1024:.1f} KB)")
    except Exception as e:
        print(f" -> Failed: {e}")

if __name__ == "__main__":
    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)
    
    print("--- Updating Libraries ---")
    for filename, url in FILES.items():
        download_file(url, TARGET_DIR, filename)
    print("\n[Done] Ready.")