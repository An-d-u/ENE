"""
대화 컨텍스트 관리
최근 N개의 대화를 메모리에 유지
"""
from collections import deque
from typing import List, Dict


class ConversationContext:
    """대화 컨텍스트 관리 클래스"""
    
    def __init__(self, max_history: int = 10):
        """
        Args:
            max_history: 최대 대화 내역 개수
        """
        self.max_history = max_history
        self.history = deque(maxlen=max_history)
    
    def add_message(self, role: str, content: str):
        """
        대화 메시지 추가
        
        Args:
            role: 'user' 또는 'assistant'
            content: 메시지 내용
        """
        self.history.append({
            'role': role,
            'parts': [content]
        })
    
    def get_history(self) -> List[Dict]:
        """
        대화 내역 반환
        
        Returns:
            Gemini API 형식의 대화 내역
        """
        return list(self.history)
    
    def clear(self):
        """대화 내역 초기화"""
        self.history.clear()
    
    def get_last_n_messages(self, n: int) -> List[Dict]:
        """
        최근 N개의 메시지 반환
        
        Args:
            n: 가져올 메시지 개수
            
        Returns:
            최근 N개의 메시지
        """
        history_list = list(self.history)
        return history_list[-n:] if len(history_list) > n else history_list
