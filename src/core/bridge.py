"""
Python-JavaScript 브릿지 (QWebChannel)
"""
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThread
from datetime import datetime


class AIWorker(QThread):
    """AI 응답을 비동기로 처리하는 워커 스레드"""
    
    response_ready = pyqtSignal(str, str)  # (텍스트, 감정)
    error_occurred = pyqtSignal(str)  # 오류 메시지
    
    def __init__(self, llm_client, message, use_memory=True, images=None):
        super().__init__()
        self.llm_client = llm_client
        self.message = message
        self.use_memory = use_memory
        self.images = images or []  # 이미지 데이터 리스트
    
    def run(self):
        """스레드 실행"""
        try:
            print(f"[AI Worker] Processing message: {self.message[:50]}...")
            
            # 비동기 메서드이므로 asyncio로 실행
            import asyncio
            
            # 새 이벤트 루프 생성 (워커 스레드용)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 이미지가 있으면 멀티모달로 처리
            if self.images:
                print(f"[AI Worker] 이미지 {len(self.images)}개 포함 - 멀티모달 모드")
                response_text, emotion = loop.run_until_complete(
                    self.llm_client.send_message_with_images(self.message, self.images)
                )
            elif self.use_memory and hasattr(self.llm_client, 'send_message_with_memory'):
                print(f"[AI Worker] 메모리 활용 모드")
                response_text, emotion = loop.run_until_complete(
                    self.llm_client.send_message_with_memory(self.message)
                )
            else:
                print(f"[AI Worker] 일반 모드 (메모리 없음)")
                # 메모리 없이 일반 전송
                response_text, emotion = self.llm_client.send_message(self.message)
            
            loop.close()
            
            print(f"[AI Worker] Response: {response_text[:50]}... [{emotion}]")
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
    
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.llm_client = None
        self.memory_manager = None
        self.worker = None
        self.settings = settings
        
        # 대화 추적
        self.conversation_buffer = []  # [(role, message), ...]
        
        # 설정에서 임계값 로드 (기본값: 10)
        if settings and hasattr(settings, 'config'):
            self.summarize_threshold = settings.config.get('summarize_threshold', 10)
        else:
            self.summarize_threshold = 10
        
        print(f"[Bridge] 자동 요약 임계값: {self.summarize_threshold}개")
    
    def set_llm_client(self, client):
        """LLM 클라이언트 설정"""
        self.llm_client = client
        print(f"[Bridge] LLM client set: {client is not None}")
    
    def set_memory_manager(self, memory_manager, llm_client, user_profile=None):
        """메모리 매니저 및 사용자 프로필 설정"""
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        print(f"[Bridge] Memory manager set: {memory_manager is not None}")
        print(f"[Bridge] User profile set: {user_profile is not None}")
    
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
        
        # 타임스탬프 추가
        now = datetime.now()
        timestamp = now.strftime("%Y년 %m월 %d일 %H시 %M분")
        message_with_time = f"[현재 시각: {timestamp}]\n{message}"
        print(f"[Bridge] Message with timestamp: {message_with_time}")
        
        # 대화 버퍼에 추가 (원본 메시지 + 타임스탬프)
        self.conversation_buffer.append(("user", message, timestamp))
        
        # 이전 워커가 실행 중이면 대기
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()
        
        # 새 워커 스레드 생성 (원본 메시지 제목으로 사용, 타임스탬프 포함 메시지 전송)
        self.worker = AIWorker(self.llm_client, message_with_time)
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()
        print("[Bridge] Worker thread started")
    
    @pyqtSlot(str, str)
    def send_to_ai_with_images(self, message: str, images_json: str):
        """
        JavaScript에서 호출: 이미지와 함께 메시지 전송
        
        Args:
            message: 사용자 메시지
            images_json: 이미지 데이터 JSON 배열
        """
        import json
        
        print(f"[Bridge] Received message with images from JS")
        
        if not self.llm_client:
            print("[Bridge] LLM client not initialized")
            self.message_received.emit("AI가 초기화되지 않았어요.", "sad")
            return
        
        # 이미지 데이터 파싱
        try:
            images_data = json.loads(images_json)
            print(f"[Bridge] Parsed {len(images_data)} images")
        except Exception as e:
            print(f"[Bridge] Failed to parse images: {e}")
            images_data = []
        
        # 현재 날짜와 시간 추가
        now = datetime.now()
        timestamp = now.strftime("%Y년 %m월 %d일 %H시 %M분")
        message_with_time = f"[현재 시각: {timestamp}]\n{message}"
        
        # 대화 버퍼에 추가 (이미지는 [이미지]로 표시 + 타임스탬프)
        img_note = f" [이미지 {len(images_data)}장]" if images_data else ""
        self.conversation_buffer.append(("user", message + img_note, timestamp))
        
        # 이전 워커가 실행 중이면 대기
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()
        
        # 새 워커 스레드 생성 (이미지 포함)
        self.worker = AIWorker(
            self.llm_client, 
            message_with_time,
            images=images_data
        )
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()
        print(f"[Bridge] Worker thread started with {len(images_data)} images")

    
    def _on_response_ready(self, text: str, emotion: str):
        """AI 응답 준비 완료"""
        print(f"[Bridge] Sending response to JS: {text} [{emotion}]")
        self.message_received.emit(text, emotion)
        
        # 대화 버퍼에 응답 추가 (+ 타임스탬프)
        now = datetime.now()
        timestamp = now.strftime("%Y년 %m월 %d일 %H시 %M분")
        self.conversation_buffer.append(("assistant", text, timestamp))
        
        # 자동 요약 확인
        self._check_auto_summarize()
    
    def _check_auto_summarize(self):
        """자동 요약 확인"""
        if not self.memory_manager:
            return
        
        if len(self.conversation_buffer) >= self.summarize_threshold:
            print(f"[Bridge] 대화 {len(self.conversation_buffer)}개 - 자동 요약 트리거")
            
            # QThread에서 실행되므로 새 이벤트 루프 생성
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._auto_summarize())
                loop.close()
            except Exception as e:
                print(f"[Bridge] 자동 요약 실패: {e}")
                import traceback
                traceback.print_exc()
    
    async def _auto_summarize(self):
        """대화 자동 요약 및 사용자 정보 추출"""
        if not self.conversation_buffer or not self.memory_manager or not self.llm_client:
            return
        
        try:
            print(f"[Bridge] 대화 요약 시작 ({len(self.conversation_buffer)}개 메시지)")
            
            # 대화 내용
            messages = self.conversation_buffer.copy()
            
            # 원본 메시지 추출 (타임스탬프 제외)
            original_messages = []
            for item in messages:
                if len(item) == 3:
                    original_messages.append(item[1])  # (role, msg, time)
                else:
                    original_messages.append(item[1])  # (role, msg)
            
            # LLM으로 요약 + 사용자 정보 생성
            summary, user_facts = await self.llm_client.summarize_conversation(messages)
            
            # 메모리에 요약 저장
            await self.memory_manager.add_summary(
                summary=summary,
                original_messages=original_messages,
                is_important=False
            )
            
            # 사용자 정보 저장
            if user_facts and hasattr(self, 'user_profile') and self.user_profile:
                print(f"[Bridge] 마스터 정보 {len(user_facts)}개 저장")
                for fact in user_facts:
                    self.user_profile.add_fact(
                        content=fact,
                        category="fact",
                        source=f"대화 요약 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
                    )
            
            # 버퍼 클리어
            self.conversation_buffer = []
            
            print(f"[Bridge] 대화 요약 완료: {summary[:50]}...")
            if user_facts:
                print(f"[Bridge] 마스터 정보: {user_facts}")
            
        except Exception as e:
            print(f"[Bridge] 자동 요약 실패: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_error(self, error_msg: str):
        """오류 발생"""
        print(f"[Bridge] Error occurred: {error_msg}")
        self.message_received.emit("음... 무슨 일이 있었나봐요.", "confused")
    
    @pyqtSlot()
    def clear_conversation(self):
        """대화 내역 초기화"""
        # 남은 대화가 있으면 요약
        if self.memory_manager and len(self.conversation_buffer) >= 2:  # 최소 2개 이상
            print(f"[Bridge] 대화 클리어 전 남은 {len(self.conversation_buffer)}개 메시지 요약")
            
            # 비동기로 요약 실행
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._auto_summarize())
                loop.close()
            except Exception as e:
                print(f"[Bridge] 클리어 시 요약 실패: {e}")
        
        # 대화 버퍼 클리어
        self.conversation_buffer = []
        
        # LLM 컨텍스트 초기화
        if self.llm_client:
            self.llm_client.clear_context()
            print("[Bridge] Conversation cleared")
    
    @pyqtSlot(str)
    def log_from_js(self, message: str):
        """JavaScript에서 로그 받기"""
        print(f"[JS] {message}")
