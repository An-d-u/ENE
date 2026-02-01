"""
Gemini LLM 클라이언트 (google-genai SDK 사용)
"""
import re
from typing import Tuple
from google import genai

from .prompt import get_system_prompt, get_available_emotions


class GeminiClient:
    """Gemini API 클라이언트"""
    
    def __init__(self, api_key: str, model_name: str = "gemini-3-flash-preview"):
        """
        Args:
            api_key: Gemini API 키
            model_name: 사용할 모델 이름
        """
        # genai 클라이언트 초기화
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        
        # Chat 세션 생성
        self.chat = self.client.chats.create(
            model=self.model_name,
            config={
                'system_instruction': get_system_prompt(),
                'temperature': 0.9,
            }
        )
        
        print(f"[LLM] Chat session created with model: {self.model_name}")
    
    def send_message(self, message: str) -> Tuple[str, str]:
        """
        메시지 전송 및 응답 받기
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그) 튜플
        """
        try:
            print(f"[LLM] Sending message: {message}")
            
            # Chat 세션으로 메시지 전송
            response = self.chat.send_message(message)
            
            # 응답 텍스트 추출
            response_text = response.text
            print(f"[LLM] Received response: {response_text[:50]}...")
            
            # 응답에서 텍스트와 감정 분리
            text, emotion = self._parse_response(response_text)
            
            return text, emotion
            
        except Exception as e:
            print(f"Gemini API 오류: {e}")
            import traceback
            traceback.print_exc()
            return "죄송해요... 지금은 답변할 수 없어요.", "sad"
    
    def _parse_response(self, response: str) -> Tuple[str, str]:
        """
        응답에서 텍스트와 감정 태그 분리
        
        Args:
            response: LLM 응답
            
        Returns:
            (텍스트, 감정) 튜플
        """
        # 감정 태그 패턴
        emotions = get_available_emotions()
        emotion_pattern = r'\[(' + '|'.join(emotions) + r')\]'
        
        # 감정 태그 찾기 (대소문자 무시)
        match = re.search(emotion_pattern, response, re.IGNORECASE)
        
        if match:
            emotion = match.group(1).lower()
            # 감정 태그 제거한 텍스트
            text = response[:match.start()].strip()
            return text, emotion
        
        # 감정 태그가 없으면 기본값
        return response.strip(), 'smile'
    
    def clear_context(self):
        """대화 컨텍스트 초기화 - 새로운 Chat 세션 생성"""
        self.chat = self.client.chats.create(
            model=self.model_name,
            config={
                'system_instruction': get_system_prompt(),
                'temperature': 0.9,
            }
        )
        print("[LLM] Chat session reset")
    
    def get_conversation_history(self):
        """대화 내역 반환"""
        # Chat 세션에서 히스토리를 가져올 수 있다면 반환
        if hasattr(self.chat, 'history'):
            return self.chat.history
        return []
