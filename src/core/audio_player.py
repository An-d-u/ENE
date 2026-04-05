"""
오디오 재생 관리
"""
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer, QUrl, QObject, pyqtSignal

if TYPE_CHECKING:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer


def _load_qt_multimedia():
    from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

    return QAudioOutput, QMediaDevices, QMediaPlayer


def _load_qt_streaming_audio():
    from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

    return QAudio, QAudioFormat, QAudioSink, QMediaDevices


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
        self.stream_sink = None
        self.stream_device = None
        self._stream_pending_pcm = bytearray()
        self._stream_finished = False
        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.timeout.connect(self._flush_stream_pcm)

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

    def start_stream(self, sample_rate: int, channels: int = 1, sample_width: int = 2):
        """PCM 스트리밍 재생을 시작한다."""
        try:
            self.stop()

            QAudio, QAudioFormat, QAudioSink, QMediaDevices = _load_qt_streaming_audio()

            audio_format = QAudioFormat()
            audio_format.setSampleRate(max(1, int(sample_rate)))
            audio_format.setChannelCount(max(1, int(channels)))
            if int(sample_width) == 1:
                audio_format.setSampleFormat(QAudioFormat.SampleFormat.UInt8)
            elif int(sample_width) == 2:
                audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            else:
                audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int32)

            target_device = self.resolve_output_device(self.output_device_id)
            if target_device is None:
                target_device = QMediaDevices.defaultAudioOutput()

            self.stream_sink = QAudioSink(target_device, audio_format)
            self.stream_sink.setVolume(self.audio_output.volume())
            self.stream_sink.stateChanged.connect(self._on_stream_state_changed)
            self.stream_device = self.stream_sink.start()
            self._stream_pending_pcm.clear()
            self._stream_finished = False
            print(
                f"[AudioPlayer] Streaming audio started: {audio_format.sampleRate()}Hz, "
                f"{audio_format.channelCount()}ch, format={audio_format.sampleFormat().name}"
            )
        except Exception as e:
            print(f"[AudioPlayer] Error starting stream audio: {e}")
            self.playback_error.emit(str(e))

    def append_stream_pcm(self, pcm_data: bytes):
        """스트리밍 PCM 청크를 재생 버퍼에 추가한다."""
        if not pcm_data:
            return
        self._stream_pending_pcm.extend(pcm_data)
        self._flush_stream_pcm()

    def finish_stream(self):
        """더 이상 들어올 PCM이 없음을 표시한다."""
        self._stream_finished = True
        self._flush_stream_pcm()
        if self.stream_device is not None and not self._stream_pending_pcm:
            try:
                self.stream_device.close()
            except Exception:
                pass
    
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
        self._stop_stream_playback()

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
        if self.stream_sink is not None:
            self.stream_sink.setVolume(volume)
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

    def _flush_stream_pcm(self):
        if self.stream_sink is None or self.stream_device is None:
            return

        while self._stream_pending_pcm:
            bytes_free = int(self.stream_sink.bytesFree())
            if bytes_free <= 0:
                break
            chunk = bytes(self._stream_pending_pcm[:bytes_free])
            written = int(self.stream_device.write(chunk))
            if written <= 0:
                break
            del self._stream_pending_pcm[:written]

        if self._stream_pending_pcm:
            self._stream_timer.start(5)
            return

        if self._stream_finished and self.stream_device is not None:
            try:
                self.stream_device.close()
            except Exception:
                pass

    def _stop_stream_playback(self):
        if self._stream_timer.isActive():
            self._stream_timer.stop()
        self._stream_pending_pcm.clear()
        self._stream_finished = False
        if self.stream_device is not None:
            try:
                self.stream_device.close()
            except Exception:
                pass
            self.stream_device = None
        if self.stream_sink is not None:
            try:
                self.stream_sink.stop()
            except Exception:
                pass
            self.stream_sink = None

    def _on_stream_state_changed(self, state):
        try:
            QAudio, _, _, _ = _load_qt_streaming_audio()
            error = self.stream_sink.error() if self.stream_sink is not None else QAudio.Error.NoError
        except Exception:
            QAudio = None
            error = None

        if self._stream_pending_pcm:
            self._flush_stream_pcm()

        if (
            QAudio is not None
            and state == QAudio.State.IdleState
            and self._stream_finished
            and not self._stream_pending_pcm
        ):
            print("[AudioPlayer] Streaming playback finished")
            self._stop_stream_playback()
            self.playback_finished.emit()
            return

        if (
            QAudio is not None
            and state == QAudio.State.StoppedState
            and error not in (None, QAudio.Error.NoError, QAudio.Error.UnderrunError)
        ):
            error_text = f"Streaming audio error: {error}"
            print(f"[AudioPlayer] {error_text}")
            self.playback_error.emit(error_text)
    
    def cleanup(self):
        """리소스 정리"""
        self.stop()
        if self.temp_file:
            try:
                Path(self.temp_file).unlink(missing_ok=True)
            except Exception:
                pass
