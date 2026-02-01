"""
Python-JavaScript 브릿지 (QWebChannel)
"""
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThread


class AIWorker(QThread):
    """AI 응답을 비동기로 처리하는 워커 스레드"""
    
    response_ready = pyqtSignal(str, str)  # (텍스트, 감정)
    error_occurred = pyqtSignal(str)  # 오류 메시지
    
    def __init__(self, llm_client, message):
        super().__init__()
        self.llm_client = llm_client
        self.message = message
    
    def run(self):
        """스레드 실행"""
        try:
            print(f"[AI Worker] Processing message: {self.message}")
            response_text, emotion = self.llm_client.send_message(self.message)
            print(f"[AI Worker] Response: {response_text} [{emotion}]")
            self.response_ready.emit(response_text, emotion)
        except Exception as e:
            print(f"[AI Worker] Error: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))


class WebBridge(QObject):
    """Python과 JavaScript 간 통신 브릿지"""
    
    # Python -> JavaScript 시그널
    message_received = pyqtSignal(str, str)  # (텍스트, 감정)
    expression_changed = pyqtSignal(str)     # 표정 변경
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.llm_client = None
        self.worker = None
    
    def set_llm_client(self, client):
        """LLM 클라이언트 설정"""
        self.llm_client = client
        print(f"[Bridge] LLM client set: {client is not None}")
    
    @pyqtSlot(str)
    def send_to_ai(self, message: str):
        """
        JavaScript에서 호출: 사용자 메시지를 AI에 전송
        
        Args:
            message: 사용자 메시지
        """
        print(f"[Bridge] Received message from JS: {message}")
        
        if not self.llm_client:
            print("[Bridge] LLM client not initialized")
            self.message_received.emit("AI가 초기화되지 않았어요.", "sad")
            return
        
        # 이전 워커가 실행 중이면 대기
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()
        
        # 새 워커 스레드 생성
        self.worker = AIWorker(self.llm_client, message)
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()
        print("[Bridge] Worker thread started")
    
    def _on_response_ready(self, text: str, emotion: str):
        """AI 응답 준비 완료"""
        print(f"[Bridge] Sending response to JS: {text} [{emotion}]")
        self.message_received.emit(text, emotion)
    
    def _on_error(self, error_msg: str):
        """오류 발생"""
        print(f"[Bridge] Error occurred: {error_msg}")
        self.message_received.emit("음... 무슨 일이 있었나봐요.", "confused")
    
    @pyqtSlot()
    def clear_conversation(self):
        """대화 내역 초기화"""
        if self.llm_client:
            self.llm_client.clear_context()
            print("[Bridge] Conversation cleared")
    
    @pyqtSlot(str)
    def log_from_js(self, message: str):
        """JavaScript에서 로그 받기"""
        print(f"[JS] {message}")
