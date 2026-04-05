"""
오디오 파일 분석 및 립싱크 데이터 생성
"""
import struct
import wave
from dataclasses import dataclass
import numpy as np
from typing import List, Tuple
from pathlib import Path


@dataclass(frozen=True)
class StreamingAudioFormat:
    """스트리밍 PCM 재생에 필요한 오디오 포맷 정보."""

    sample_rate: int
    channels: int
    sample_width: int


class StreamingWavDecoder:
    """HTTP chunked WAV 스트림에서 헤더와 PCM 본문을 분리한다."""

    def __init__(self):
        self._header_buffer = bytearray()
        self._header_parsed = False
        self.audio_format: StreamingAudioFormat | None = None

    def push(self, chunk: bytes) -> tuple[StreamingAudioFormat | None, bytes]:
        if not chunk:
            return self.audio_format, b""

        if self._header_parsed:
            return self.audio_format, bytes(chunk)

        self._header_buffer.extend(chunk)
        parsed = self._try_parse_header(bytes(self._header_buffer))
        if parsed is None:
            return None, b""

        audio_format, data_offset = parsed
        self.audio_format = audio_format
        self._header_parsed = True
        pcm_bytes = bytes(self._header_buffer[data_offset:])
        self._header_buffer.clear()
        return audio_format, pcm_bytes

    def _try_parse_header(self, data: bytes) -> tuple[StreamingAudioFormat, int] | None:
        if len(data) < 12:
            return None
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError("지원하지 않는 WAV 스트림 헤더입니다.")

        offset = 12
        parsed_format: StreamingAudioFormat | None = None
        data_offset: int | None = None

        while offset + 8 <= len(data):
            chunk_id = data[offset:offset + 4]
            chunk_size = struct.unpack("<I", data[offset + 4:offset + 8])[0]
            chunk_data_start = offset + 8
            chunk_data_end = chunk_data_start + chunk_size

            if chunk_id == b"fmt ":
                if chunk_data_end > len(data):
                    return None
                if chunk_size < 16:
                    raise ValueError("WAV fmt 청크 길이가 올바르지 않습니다.")
                audio_format, channels, sample_rate, _byte_rate, _block_align, bits_per_sample = struct.unpack(
                    "<HHIIHH",
                    data[chunk_data_start:chunk_data_start + 16],
                )
                if audio_format != 1:
                    raise ValueError("PCM WAV 스트림만 지원합니다.")
                if bits_per_sample % 8 != 0:
                    raise ValueError("지원하지 않는 샘플 폭입니다.")
                parsed_format = StreamingAudioFormat(
                    sample_rate=int(sample_rate),
                    channels=int(channels),
                    sample_width=int(bits_per_sample // 8),
                )
            elif chunk_id == b"data":
                data_offset = chunk_data_start
                break

            if chunk_data_end > len(data):
                return None

            offset = chunk_data_end + (chunk_size % 2)

        if parsed_format is None or data_offset is None:
            return None
        return parsed_format, data_offset


class RealtimeLipSyncAnalyzer:
    """실시간 PCM 청크에서 프레임 단위 입 모양 값을 계산한다."""

    def __init__(self, sample_rate: int, channels: int = 1, sample_width: int = 2, frame_duration_ms: int = 50):
        self.sample_rate = max(1, int(sample_rate))
        self.channels = max(1, int(channels))
        self.sample_width = max(1, int(sample_width))
        self.frame_duration_ms = max(1, int(frame_duration_ms))
        self._pending_pcm = bytearray()
        self._bytes_per_audio_frame = self.channels * self.sample_width
        self._pcm_bytes_per_window = max(
            self._bytes_per_audio_frame,
            int(self.sample_rate * self.frame_duration_ms / 1000) * self._bytes_per_audio_frame,
        )

    def push_pcm(self, pcm_data: bytes) -> list[float]:
        if pcm_data:
            self._pending_pcm.extend(pcm_data)

        values: list[float] = []
        while len(self._pending_pcm) >= self._pcm_bytes_per_window:
            frame = bytes(self._pending_pcm[:self._pcm_bytes_per_window])
            del self._pending_pcm[:self._pcm_bytes_per_window]
            values.append(self._calculate_mouth_value(frame))
        return values

    def finalize(self) -> list[float]:
        if not self._pending_pcm:
            return []
        remaining = bytes(self._pending_pcm)
        self._pending_pcm.clear()
        return [self._calculate_mouth_value(remaining)]

    def _calculate_mouth_value(self, pcm_frame: bytes) -> float:
        if not pcm_frame:
            return 0.0

        if self.sample_width == 1:
            audio_array = np.frombuffer(pcm_frame, dtype=np.uint8)
            normalized = (audio_array.astype(np.float32) - 128.0) / 128.0
        elif self.sample_width == 2:
            audio_array = np.frombuffer(pcm_frame, dtype=np.int16)
            normalized = audio_array.astype(np.float32) / 32768.0
        else:
            audio_array = np.frombuffer(pcm_frame, dtype=np.int32)
            normalized = audio_array.astype(np.float32) / float(2 ** (self.sample_width * 8 - 1))

        if self.channels > 1 and len(normalized) >= self.channels:
            trimmed = len(normalized) - (len(normalized) % self.channels)
            normalized = normalized[:trimmed].reshape(-1, self.channels).mean(axis=1)

        rms = float(np.sqrt(np.mean(normalized ** 2))) if len(normalized) else 0.0
        return min(rms * 12.0, 1.0)


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
