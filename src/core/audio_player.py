"""
오디오 재생 관리
"""
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, QObject, pyqtSignal
import os
import tempfile
from pathlib import Path


class AudioPlayer(QObject):
    """오디오 재생 관리자"""
    
    playback_finished = pyqtSignal()  # 재생 완료 시그널
    playback_error = pyqtSignal(str)  # 재생 오류 시그널
    
    def __init__(self):
        super().__init__()
        
        # Qt 멀티미디어 플레이어 초기화
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        # 시그널 연결
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.errorOccurred.connect(self._on_error)
        
        # 임시 파일 경로
        self.temp_file = None
        
        # 볼륨 설정 (0.0 ~ 1.0)
        self.audio_output.setVolume(0.8)
        
        print("[AudioPlayer] Initialized")
    
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
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.player.stop()
    
    def set_volume(self, volume: float):
        """
        볼륨 설정
        
        Args:
            volume: 0.0 ~ 1.0
        """
        volume = max(0.0, min(1.0, volume))
        self.audio_output.setVolume(volume)
        print(f"[AudioPlayer] Volume set to {volume:.2f}")
    
    def _on_media_status_changed(self, status):
        """미디어 상태 변경 이벤트"""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
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
