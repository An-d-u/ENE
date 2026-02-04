"""
Gemini LLM 클라이언트 (google-genai SDK 사용)
"""
import re
from typing import Tuple
from google import genai

from .prompt import get_system_prompt, get_available_emotions


class GeminiClient:
    """Gemini API 클라이언트"""
    
    def __init__(
        self, 
        api_key: str, 
        model_name: str = "gemini-3-flash-preview",
        memory_manager=None
    ):
        """
        Args:
            api_key: Gemini API 키
            model_name: 사용할 모델 이름
            memory_manager: 메모리 매니저 (옵션)
        """
        # genai 클라이언트 초기화
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.memory_manager = memory_manager
        
        # Chat 세션 생성
        self.chat = self.client.chats.create(
            model=self.model_name,
            config={
                'system_instruction': get_system_prompt(),
                'temperature': 0.9,
            }
        )
        
        print(f"[LLM] Chat session created with model: {self.model_name}")
        if self.memory_manager:
            print("[LLM] Memory manager connected")
    
    async def send_message_with_memory(self, message: str) -> Tuple[str, str]:
        """
        메모리를 활용한 메시지 전송
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그) 튜플
        """
        # 메모리 컨텍스트 구성
        memory_context = await self._build_memory_context(message)
        
        # 메모리가 있으면 메시지 앞에 추가
        if memory_context:
            enhanced_message = f"{memory_context}\n\n{message}"
            print(f"[LLM] 메모리 컨텍스트 추가 (길이: {len(memory_context)})")
        else:
            enhanced_message = message
        
        # 일반 메시지 전송
        return self.send_message(enhanced_message)
    
    async def _build_memory_context(self, query: str) -> str:
        """
        메모리 컨텍스트 구성
        
        Args:
            query: 사용자 쿼리
            
        Returns:
            메모리 컨텍스트 문자열
        """
        if not self.memory_manager:
            print("[LLM] 메모리 매니저 없음")
            return ""
        
        context_parts = []
        
        # 1. 중요 기억 가져오기
        important_memories = self.memory_manager.get_important()
        if important_memories:
            print(f"[LLM] 중요 기억 {len(important_memories)}개 발견")
            context_parts.append("[중요한 기억]")
            for memory in important_memories[:3]:  # 최대 3개
                context_parts.append(f"- {memory.summary}")
                print(f"  ⭐ {memory.summary[:50]}...")
        else:
            print("[LLM] 중요 기억 없음")
        
        # 2. 유사 기억 검색
        try:
            similar_memories = await self.memory_manager.find_similar(
                query, 
                top_k=3,
                min_similarity=0.5
            )
            
            if similar_memories:
                print(f"[LLM] 유사 기억 {len(similar_memories)}개 발견")
                context_parts.append("\n[관련된 과거 기억]")
                for memory, similarity in similar_memories:
                    context_parts.append(f"- {memory.summary}")
                    print(f"  [{similarity:.2f}] {memory.summary[:50]}...")
            else:
                print("[LLM] 유사 기억 없음")
        
        except Exception as e:
            print(f"[LLM] 유사 기억 검색 실패: {e}")
            import traceback
            traceback.print_exc()
        
        # 3. 최근 기억도 추가 (임베딩 없어도 사용 가능)
        recent_memories = self.memory_manager.get_recent(count=2)
        if recent_memories and not context_parts:  # 중요/유사 기억이 없을 때만
            print(f"[LLM] 최근 기억 {len(recent_memories)}개 사용")
            context_parts.append("[최근 대화 기록]")
            for memory in recent_memories:
                # 날짜 포맷 (예: 2026-02-03 21:15)
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(memory.timestamp)
                    date_str = dt.strftime("%Y년 %m월 %d일")
                    context_parts.append(f"- [{date_str}] {memory.summary}")
                    print(f"  📝 [{date_str}] {memory.summary[:40]}...")
                except:
                    context_parts.append(f"- {memory.summary}")
                    print(f"  📝 {memory.summary[:50]}...")
        
        # 컨텍스트 문자열 생성
        if context_parts:
            result = "\n".join(context_parts)
            print(f"[LLM] 총 메모리 컨텍스트: {len(result)}자")
            return result
        
        print("[LLM] 사용 가능한 기억 없음")
        return ""
    
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
            print(f"[LLM] Error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        """
        대화 내용 요약 및 사용자 정보 추출
        
        Args:
            messages: [(role, content), ...] 형식의 메시지 리스트
            
        Returns:
            (요약 텍스트, 사용자 정보 목록) 튜플
        """
        try:
            # 현재 시간 가져오기
            from datetime import datetime
            now = datetime.now()
            time_str = now.strftime("%Y년 %m월 %d일 %H시 %M분")
            
            # 대화 내용을 하나의 문자열로 구성
            conversation_text = "\n".join([
                f"{role}: {content}" for role, content in messages
            ])
            
            # 요약 + 정보 추출 프롬프트
            summarize_prompt = f"""다음 대화를 요약하고, 마스터에 대한 새로운 정보를 추출해주세요.

대화:
{conversation_text}

다음 형식으로 답변해주세요:

[요약]
{time_str}에 이루어진 대화 요약 (2-3문장)

[마스터 정보]
- 마스터에 대해 새로 알게 된 정보나 사실 나열 (없으면 "없음")
- 예: "커피를 좋아함", "프로그래머로 일함", "고양이 알러지가 있음"
"""
            
            print(f"[LLM] 대화 요약 및 정보 추출 중... (메시지 수: {len(messages)})")
            
            # 일회성 요청으로 요약 생성 (Chat 세션과 별도)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=summarize_prompt,
                config={'temperature': 0.5}  # 요약은 더 일관성 있게
            )
            
            response_text = response.text.strip()
            
            # 응답 파싱
            summary, user_facts = self._parse_summary_response(response_text)
            
            print(f"[LLM] 요약 생성 완료: {summary[:50]}...")
            if user_facts:
                print(f"[LLM] 마스터 정보 {len(user_facts)}개 추출: {user_facts}")
            
            return summary, user_facts
            
        except Exception as e:
            print(f"[LLM] 요약 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            # 실패 시 간단한 요약 반환
            return f"대화 {len(messages)}개 메시지", []
    
    def _parse_summary_response(self, response_text: str) -> tuple[str, list[str]]:
        """
        요약 응답 파싱 ([요약] 및 [마스터 정보] 분리)
        
        Args:
            response_text: LLM 응답 텍스트
            
        Returns:
            (요약, 사용자 정보 목록) 튜플
        """
        summary = ""
        user_facts = []
        
        try:
            lines = response_text.split('\n')
            current_section = None
            
            for line in lines:
                line = line.strip()
                
                if '[요약]' in line or 'Summary' in line:
                    current_section = 'summary'
                    continue
                elif '[마스터 정보]' in line or 'Master Info' in line or '[사용자 정보]' in line:
                    current_section = 'facts'
                    continue
                
                if not line:
                    continue
                
                if current_section == 'summary':
                    summary += line + " "
                elif current_section == 'facts':
                    # "- " 로 시작하거나 "없음"이 아닌 경우
                    if line.startswith('-'):
                        fact = line[1:].strip()
                        if fact and fact.lower() not in ['없음', 'none', '없습니다']:
                            user_facts.append(fact)
            
            summary = summary.strip()
            
            # 섹션이 없는 경우 전체를 요약으로 간주
            if not summary:
                summary = response_text.strip()
            
        except Exception as e:
            print(f"[LLM] 응답 파싱 실패: {e}")
            summary = response_text.strip()
        
        return summary, user_facts
    
    def _parse_response(self, response_text: str) -> Tuple[str, str]:
        """
        응답 텍스트에서 감정 태그 추출
        
        Args:
            response_text: AI 응답 텍스트
            
        Returns:
            (텍스트, 감정) 튜플
        """
        # [emotion] 패턴 찾기
        emotion_pattern = r'\[(\w+)\]'
        matches = re.findall(emotion_pattern, response_text)
        
        # 감정 태그 제거한 텍스트
        clean_text = re.sub(emotion_pattern, '', response_text).strip()
        
        # 유효한 감정 찾기
        available_emotions = get_available_emotions()
        emotion = 'normal'  # 기본값
        
        for match in matches:
            if match.lower() in available_emotions:
                emotion = match.lower()
                break
        
        return clean_text, emotion
    
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
