"""
오디오 재생 관리
"""
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QUrl, QObject, pyqtSignal

if TYPE_CHECKING:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer


def _load_qt_multimedia():
    from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

    return QAudioOutput, QMediaDevices, QMediaPlayer


class AudioPlayer(QObject):
    """오디오 재생 관리자"""
    
    playback_finished = pyqtSignal()  # 재생 완료 시그널
    playback_error = pyqtSignal(str)  # 재생 오류 시그널
    
    def __init__(self, output_device_id: str = "", volume: float = 0.8):
        super().__init__()

        QAudioOutput, _, QMediaPlayer = _load_qt_multimedia()

        # Qt 멀티미디어 플레이어 초기화
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self._media_player_class = QMediaPlayer
        self.player.setAudioOutput(self.audio_output)
        
        # 시그널 연결
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.errorOccurred.connect(self._on_error)
        
        # 임시 파일 경로
        self.temp_file = None

        # 현재 출력 장치 상태
        self.output_device_id = ""

        self.set_output_device(output_device_id)
        self.set_volume(volume)
        
        print("[AudioPlayer] Initialized")

    @staticmethod
    def serialize_device_id(device_id) -> str:
        """QAudioDevice ID를 저장 가능한 문자열로 정규화한다."""
        if device_id in (None, ""):
            return ""
        if isinstance(device_id, str):
            return device_id.strip()
        if isinstance(device_id, (bytes, bytearray, memoryview)):
            return bytes(device_id).hex()
        try:
            return bytes(device_id).hex()
        except Exception:
            return str(device_id).strip()

    @staticmethod
    def normalize_volume(volume: float) -> float:
        """Qt 오디오 출력용 볼륨 범위(0.0 ~ 1.0)로 정규화한다."""
        return max(0.0, min(1.0, float(volume)))

    @classmethod
    def list_output_devices(cls) -> list[dict]:
        """사용 가능한 오디오 출력 장치 목록을 반환한다."""
        _, QMediaDevices, _ = _load_qt_multimedia()
        default_device = QMediaDevices.defaultAudioOutput()
        default_device_id = cls.serialize_device_id(default_device.id())
        devices = []
        for device in QMediaDevices.audioOutputs():
            device_id = cls.serialize_device_id(device.id())
            devices.append(
                {
                    "id": device_id,
                    "name": device.description(),
                    "is_default": device_id == default_device_id,
                }
            )
        return devices

    @classmethod
    def resolve_output_device(cls, device_id: str, devices=None):
        """저장된 장치 ID와 일치하는 QAudioDevice를 찾는다."""
        normalized_id = str(device_id or "").strip()
        if not normalized_id:
            return None
        if devices is None:
            _, QMediaDevices, _ = _load_qt_multimedia()
            available_devices = QMediaDevices.audioOutputs()
        else:
            available_devices = devices
        for device in available_devices:
            if cls.serialize_device_id(device.id()) == normalized_id:
                return device
        return None
    
    def play(self, audio_data: bytes):
        """
        오디오 데이터 재생
        
        Args:
            audio_data: WAV 오디오 바이트
        """
        try:
            # 이전 재생 정지
            self.stop()
            
            # 이전 임시 파일 정리 (재생이 완전히 멈춘 후)
            if self.temp_file:
                old_file = self.temp_file
                self.temp_file = None
                
                # QTimer를 사용해 약간 지연 후 삭제
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, lambda: self._delete_old_file(old_file))
            
            # 새 임시 파일 생성
            temp_fd, self.temp_file = tempfile.mkstemp(suffix=".wav")
            with os.fdopen(temp_fd, 'wb') as f:
                f.write(audio_data)
            
            print(f"[AudioPlayer] Playing audio from temp file: {self.temp_file}")
            
            # QMediaPlayer로 재생
            file_url = QUrl.fromLocalFile(self.temp_file)
            self.player.setSource(file_url)
            self.player.play()
            
        except Exception as e:
            print(f"[AudioPlayer] Error playing audio: {e}")
            self.playback_error.emit(str(e))
    
    def _delete_old_file(self, file_path: str):
        """이전 임시 파일 삭제 (지연 실행)"""
        try:
            Path(file_path).unlink(missing_ok=True)
            print(f"[AudioPlayer] Cleaned old temp file: {file_path}")
        except Exception:
            # 조용히 무시 (파일이 이미 삭제되었거나 접근 불가)
            pass
    
    def stop(self):
        """재생 중지"""
        if self.player.playbackState() != self._media_player_class.PlaybackState.StoppedState:
            self.player.stop()

    def set_output_device(self, output_device_id: str):
        """재생 출력 장치를 설정한다. 비어 있으면 시스템 기본 장치를 사용한다."""
        normalized_id = str(output_device_id or "").strip()
        target_device = self.resolve_output_device(normalized_id)
        if target_device is None:
            _, QMediaDevices, _ = _load_qt_multimedia()
            self.audio_output.setDevice(QMediaDevices.defaultAudioOutput())
            self.output_device_id = ""
            print("[AudioPlayer] Output device set to system default")
            return

        self.audio_output.setDevice(target_device)
        self.output_device_id = self.serialize_device_id(target_device.id())
        print(f"[AudioPlayer] Output device set: {target_device.description()}")
    
    def set_volume(self, volume: float):
        """
        볼륨 설정
        
        Args:
            volume: 0.0 ~ 1.0
        """
        volume = self.normalize_volume(volume)
        self.audio_output.setVolume(volume)
        print(f"[AudioPlayer] Volume set to {volume:.2f}")
    
    def _on_media_status_changed(self, status):
        """미디어 상태 변경 이벤트"""
        if status == self._media_player_class.MediaStatus.EndOfMedia:
            print("[AudioPlayer] Playback finished")
            self.playback_finished.emit()
            
            # 임시 파일 삭제는 다음 재생 시에 처리
            # (Windows에서 QMediaPlayer가 파일을 잠그고 있어 즉시 삭제 불가)
    
    def _on_error(self, error, error_string):
        """에러 발생 이벤트"""
        print(f"[AudioPlayer] Error: {error_string}")
        self.playback_error.emit(error_string)
    
    def cleanup(self):
        """리소스 정리"""
        self.stop()
        if self.temp_file:
            try:
                Path(self.temp_file).unlink(missing_ok=True)
            except Exception:
                pass
