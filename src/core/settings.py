"""
ENE 설정 관리 모듈
사용자 설정을 JSON 파일로 저장/로드
"""
import json
import os
from pathlib import Path


class Settings:
    """애플리케이션 설정 관리 클래스"""
    
    DEFAULT_CONFIG = {
        'window_x': 100,
        'window_y': 100,
        'window_width': 400,
        'window_height': 600,
        'zoom_level': 1.0,
        'show_drag_bar': True,
        'model_scale': 1.0,
        'model_x_percent': 50,  # 0-100%
        'model_y_percent': 50,  # 0-100%
        'mouse_tracking_enabled': True,  # 마우스 트래킹
        'gemini_api_key': '',  # Gemini API 키
    }
    
    def __init__(self, config_path: str = 'config.json'):
        """
        Args:
            config_path: 설정 파일 경로
        """
        self.config_path = Path(config_path)
        self.config = self.load()
    
    def load(self) -> dict:
        """설정 파일 로드. 없으면 기본값 반환"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                # 기본값과 병합 (누락된 키 보완)
                return {**self.DEFAULT_CONFIG, **loaded_config}
            except Exception as e:
                print(f"설정 파일 로드 실패: {e}")
                return self.DEFAULT_CONFIG.copy()
        return self.DEFAULT_CONFIG.copy()
    
    def save(self):
        """현재 설정을 파일에 저장"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"설정 파일 저장 실패: {e}")
    
    def get(self, key: str, default=None):
        """설정 값 가져오기"""
        return self.config.get(key, default)
    
    def set(self, key: str, value):
        """설정 값 변경"""
        self.config[key] = value
    
    def update(self, updates: dict):
        """여러 설정 값 한 번에 업데이트"""
        self.config.update(updates)
