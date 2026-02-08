"""
오디오 파일 분석 및 립싱크 데이터 생성
"""
import wave
import numpy as np
from typing import List, Tuple
from pathlib import Path


class AudioAnalyzer:
    """오디오 파일을 분석하여 립싱크 데이터 생성"""
    
    def __init__(self, frame_duration_ms: int = 50):
        """
        Args:
            frame_duration_ms: 분석 프레임 간격 (밀리초)
        """
        self.frame_duration_ms = frame_duration_ms
    
    def analyze(self, wav_path: str) -> List[Tuple[float, float]]:
        """
        WAV 파일 분석하여 립싱크 데이터 생성
        
        Args:
            wav_path: WAV 파일 경로
            
        Returns:
            [(timestamp, mouth_value), ...]
            - timestamp: 초 단위 시간
            - mouth_value: 입 벌림 정도 (0.0 ~ 1.0)
        """
        if not Path(wav_path).exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")
        
        try:
            # WAV 파일 열기
            with wave.open(wav_path, 'rb') as wf:
                # 오디오 파라미터 추출
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                n_frames = wf.getnframes()
                
                # 프레임 크기 계산 (밀리초 → 샘플 수)
                frame_size = int(sample_rate * self.frame_duration_ms / 1000)
                
                # 오디오 데이터 읽기
                audio_data = wf.readframes(n_frames)
                
                # numpy 배열로 변환
                if sample_width == 1:
                    dtype = np.uint8
                elif sample_width == 2:
                    dtype = np.int16
                else:
                    dtype = np.int32
                
                audio_array = np.frombuffer(audio_data, dtype=dtype)
                
                # 스테레오면 모노로 변환 (평균)
                if n_channels == 2:
                    audio_array = audio_array.reshape(-1, 2).mean(axis=1)
                
                # 정규화 (-1.0 ~ 1.0)
                if dtype == np.uint8:
                    audio_array = (audio_array - 128) / 128.0
                else:
                    audio_array = audio_array / (2 ** (sample_width * 8 - 1))
                
                # 프레임별 RMS 계산
                lip_sync_data = []
                for i in range(0, len(audio_array), frame_size):
                    frame = audio_array[i:i + frame_size]
                    
                    if len(frame) == 0:
                        break
                    
                    # RMS (Root Mean Square) 계산
                    rms = np.sqrt(np.mean(frame ** 2))
                    
                    # 타임스탬프 계산 (초)
                    timestamp = i / sample_rate
                    
                    # RMS를 입 벌림 값으로 변환 (0.0 ~ 1.0)
                    # RMS는 보통 0.0 ~ 0.5 정도이므로 스케일링
                    mouth_value = min(rms * 12.0, 1.0)
                    
                    lip_sync_data.append((timestamp, mouth_value))
                
                # 스무딩 적용 (부드러운 전환)
                smoothed_data = self._smooth_data(lip_sync_data)
                
                print(f"[AudioAnalyzer] Analyzed {len(smoothed_data)} frames")
                print(f"[AudioAnalyzer] Duration: {n_frames / sample_rate:.2f}s")
                
                return smoothed_data
        
        except Exception as e:
            print(f"[AudioAnalyzer] Error analyzing audio: {e}")
            raise
    
    def _smooth_data(
        self,
        data: List[Tuple[float, float]],
        window_size: int = 3
    ) -> List[Tuple[float, float]]:
        """
        립싱크 데이터 스무딩 (이동 평균)
        
        Args:
            data: [(timestamp, value), ...]
            window_size: 이동 평균 윈도우 크기
            
        Returns:
            스무딩된 데이터
        """
        if len(data) < window_size:
            return data
        
        smoothed = []
        values = [v for _, v in data]
        
        for i, (timestamp, _) in enumerate(data):
            # 이동 평균 계산
            start = max(0, i - window_size // 2)
            end = min(len(values), i + window_size // 2 + 1)
            avg_value = np.mean(values[start:end])
            
            smoothed.append((timestamp, float(avg_value)))
        
        return smoothed
