"""
Gemini LLM 클라이언트 (google-genai SDK 사용)
"""
import re
from typing import Tuple, List, Dict
from google import genai

from .prompt import get_system_prompt, get_available_emotions


class GeminiClient:
    """Gemini API 클라이언트"""
    
    def __init__(self, api_key: str, memory_manager=None, user_profile=None, settings=None, calendar_manager=None):
        """
        Gemini API 클라이언트 초기화
        
        Args:
            api_key: Gemini API 키
            memory_manager: 메모리 매니저 인스턴스 (옵션)
            user_profile: 사용자 프로필 인스턴스 (옵션)
            settings: 설정 매니저 인스턴스 (옵션)
            calendar_manager: 캘린더 매니저 인스턴스 (옵션)
        """
        # genai 클라이언트 초기화
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-3-flash-preview"
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        
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
    
    async def send_message_with_memory(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        """
        메모리를 활용한 메시지 전송
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그, 일본어 번역, 이벤트 리스트) 튜플
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
    
    async def send_message_with_images(self, message: str, images_data: list) -> Tuple[str, str, str, List[Dict]]:
        """
        이미지와 함께 메시지 전송 (멀티모달)
        
        Args:
            message: 사용자 메시지
            images_data: 이미지 데이터 리스트 [{"dataUrl": ..., "name": ...}, ...]
            
        Returns:
            (응답 텍스트, 감정 태그, 일본어 번역, 이벤트 리스트) 튜플
        """
        import base64
        from PIL import Image
        import io
        
        print(f"[LLM] 멀티모달 요청: {len(images_data)}개 이미지")
        
        try:
            # 이미지 준비
            pil_images = []
            for img_data in images_data:
                data_url = img_data.get('dataUrl', '')
                if not data_url:
                    continue
                
                # base64 디코딩
                # data:image/png;base64,... 형식에서 데이터 부분만 추출
                if ',' in data_url:
                    header, base64_data = data_url.split(',', 1)
                else:
                    base64_data = data_url
                
                try:
                    image_bytes = base64.b64decode(base64_data)
                    pil_image = Image.open(io.BytesIO(image_bytes))
                    pil_images.append(pil_image)
                    print(f"[LLM] 이미지 로드: {pil_image.size}")
                except Exception as e:
                    print(f"[LLM] 이미지 디코딩 실패: {e}")
            
            if not pil_images:
                print("[LLM] 유효한 이미지가 없음, 텍스트만 전송")
                return await self.send_message_with_memory(message)
            
            # 메모리 컨텍스트 추가
            memory_context = await self._build_memory_context(message)
            if memory_context:
                enhanced_message = f"{memory_context}\n\n{message}"
            else:
                enhanced_message = message
            
            # Gemini에 멀티모달 요청
            # contents에 이미지와 텍스트를 함께 전달
            contents = pil_images + [enhanced_message]
            
            # 토큰 계산
            await self._count_and_log_tokens(contents)
            
            print(f"[LLM] Gemini 멀티모달 요청 전송...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config={
                    'system_instruction': get_system_prompt(),
                    'temperature': 0.9
                }
            )
            
            response_text = response.text.strip()
            print(f"[LLM] 멀티모달 응답: {response_text[:100]}...")
            
            # 응답에서 텍스트, 감정, 일정 분리 (기존 메서드 활용)
            clean_text, emotion, japanese_text, events = self._parse_response(response_text)
            
            # 일본어가 있으면 로깅
            if japanese_text:
                print(f"[LLM] 일본어 번역: {japanese_text[:30]}...")
            
            # 일정이 있으면 로깅
            if events:
                print(f"[LLM] {len(events)}개 일정 추출됨")
            
            return clean_text, emotion, japanese_text, events

            
        except Exception as e:
            print(f"[LLM] 멀티모달 처리 실패: {e}")
            import traceback
            traceback.print_exc()
            return f"이미지를 처리하는 중에 문제가 생겼어요... ({str(e)[:50]})", "confused", None, []

    
    async def _build_memory_context(self, query: str) -> str:
        """
        메모리 기반 컨텍스트 구성
        
        Args:
            query: 사용자 쿼리
            
        Returns:
            컨텍스트 문자열
        """
        if not self.memory_manager:
            print("[LLM] 메모리 매니저 없음")
            return ""
        
        context_parts = []
        
        # 0. 사용자 프로필 정보 (최우선)
        if self.user_profile and hasattr(self.user_profile, 'basic_info'):
            profile_lines = ["[마스터 기본 정보]"]
            
            basic = self.user_profile.basic_info
            if basic.get('name'):
                profile_lines.append(f"- 이름: {basic['name']}")
            if basic.get('gender'):
                profile_lines.append(f"- 성별: {basic['gender']}")
            if basic.get('birthday'):
                profile_lines.append(f"- 생일: {basic['birthday']}")
            if basic.get('occupation'):
                profile_lines.append(f"- 직업: {basic['occupation']}")
            if basic.get('major'):
                profile_lines.append(f"- 전공: {basic['major']}")
            
            # 취미/선호도
            prefs = self.user_profile.preferences
            if prefs.get('likes'):
                profile_lines.append(f"- 좋아하는 것: {', '.join(prefs['likes'])}")
            
            if len(profile_lines) > 1:  # 정보가 있으면
                context_parts.append("\n".join(profile_lines))
                print(f"[LLM] 프로필 정보 포함: {len(profile_lines)-1}개 항목")
        
        # 설정값 가져오기
        settings_config = self.settings.config if self.settings else {}
        max_important = settings_config.get('max_important_memories', 3)
        max_similar = settings_config.get('max_similar_memories', 3)
        min_sim = settings_config.get('min_similarity', 0.35)
        max_recent = settings_config.get('max_recent_memories', 2)
        
        # 1. 중요 기억 가져오기
        important_memories = self.memory_manager.get_important()
        if important_memories:
            print(f"[LLM] 중요 기억 {len(important_memories)}개 발견")
            context_parts.append("\n[중요한 기억]")
            for memory in important_memories[:max_important]:
                context_parts.append(f"- {memory.summary}")
                print(f"  ⭐ {memory.summary[:50]}...")
        else:
            print("[LLM] 중요 기억 없음")
        
        # 2. 유사 기억 검색
        try:
            similar_memories = await self.memory_manager.find_similar(
                query, 
                top_k=max_similar,
                min_similarity=min_sim
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
        recent_memories = self.memory_manager.get_recent(count=max_recent)
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
        
        # 4. 다가오는 일정 추가
        if self.calendar_manager:
            upcoming = self.calendar_manager.get_upcoming_events(days=3)
            if upcoming:
                print(f"[LLM] 다가오는 일정 {len(upcoming)}개 발견")
                context_parts.append("\n[다가오는 일정]")
                for event in upcoming:
                    try:
                        from datetime import datetime
                        event_date = datetime.fromisoformat(event.date)
                        date_str = event_date.strftime("%m월 %d일")
                        
                        # 완료 여부 표시
                        status = " ✓ 완료" if event.completed else ""
                        
                        # 제목과 상세설명, 완료 상태를 한 줄로 표시
                        if event.description:
                            event_info = f"- {date_str}: {event.title} ({event.description}){status}"
                        else:
                            event_info = f"- {date_str}: {event.title}{status}"
                        
                        context_parts.append(event_info)
                        print(f"  📅 {event_info}")
                    except:
                        pass
        
        # 5. 최근 일주일 대화 횟수 추가 (오늘 제외)
        if self.calendar_manager:
            recent_counts = self.calendar_manager.get_recent_conversation_counts(days=7, exclude_today=True)
            if recent_counts:
                context_parts.append("\n[최근 대화 활동]")
                for date_str, count in recent_counts.items():
                    try:
                        from datetime import datetime
                        date_obj = datetime.fromisoformat(date_str)
                        date_display = date_obj.strftime("%m월 %d일")
                        context_parts.append(f"- {date_display}: {count}회")
                    except:
                        pass
                print(f"[LLM] 최근 대화 횟수 {len(recent_counts)}일 포함")
        
        # 컨텍스트 문자열 생성
        if context_parts:
            result = "\n".join(context_parts)
            print(f"[LLM] 총 메모리 컨텍스트: {len(result)}자")
            return result
        
        print("[LLM] 사용 가능한 기억 없음")
        return ""
    
    async def _count_and_log_tokens(self, contents):
        """
        토큰 수 계산 및 로깅
        
        Args:
            contents: 토큰을 계산할 컨텐츠 (문자열 또는 리스트)
        """
        try:
            # 시스템 프롬프트도 포함해야 정확함
            system_prompt = get_system_prompt()
            
            if isinstance(contents, str):
                full_contents = [system_prompt, contents]
            elif isinstance(contents, list):
                full_contents = [system_prompt] + contents
            else:
                full_contents = [system_prompt, str(contents)]
                
            response = self.client.models.count_tokens(
                model=self.model_name,
                contents=full_contents
            )
            
            print(f"[LLM] 🎫 Token Usage: {response.total_tokens} tokens (Prompt: {full_contents.__len__()} parts)")
            
        except Exception as e:
            print(f"[LLM] 토큰 계산 실패: {e}")

    def send_message(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        """
        메시지 전송 및 응답 받기
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그, 일본어 번역, 이벤트 리스트) 튜플
        """
        try:
            print(f"[LLM] Sending message: {message}")
            
            # 토큰 계산 (비동기로 실행하지 않고 로그만 출력)
            # 동기 메서드 내에서 비동기 호출이 어려우므로 여기서는 생략하거나
            # 별도의 동기 메서드로 구현해야 함. 일단은 생략하고 멀티모달에서만 적용
            
            # Chat 세션으로 메시지 전송
            response = self.chat.send_message(message)
            
            # 응답 텍스트 추출
            response_text = response.text
            print(f"[LLM] Received response: {response_text[:50]}...")
            
            # 응답에서 텍스트와 감정 분리
            text, emotion, japanese_text, events = self._parse_response(response_text)
            
            # 일본어가 있으면 로깅
            if japanese_text:
                print(f"[LLM] 일본어 번역: {japanese_text[:30]}...")
            
            # 일정이 있으면 로깅
            if events:
                print(f"[LLM] {len(events)}개 일정 추출됨")
            
            return text, emotion, japanese_text, events
            
        except Exception as e:
            print(f"[LLM] Error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
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
            
        # 토큰 계산
        await self._count_and_log_tokens(enhanced_message)
        
        # 일반 메시지 전송
        return self.send_message(enhanced_message)

    
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
            
            # 대화 내용을 하나의 문자열로 구성 (타임스탬프 전체 유지)
            conv_lines = []
            first_time = None
            last_time = None
            
            for item in messages:
                if len(item) == 3:
                    role, content, timestamp = item
                    # 첫/마지막 시간 기록
                    if first_time is None:
                        first_time = timestamp
                    last_time = timestamp
                    # 타임스탬프 전체 포함 (더 명확한 컨텍스트)
                    conv_lines.append(f"[{timestamp}] {role}: {content}")
                else:
                    role, content = item
                    conv_lines.append(f"{role}: {content}")
            
            conversation_text = "\n".join(conv_lines)
            
            # 대화 시간 범위
            if first_time and last_time:
                time_range = f"{first_time} ~ {last_time}"
            else:
                time_range = time_str
            
            # 현재 알고 있는 마스터 정보 가져오기
            current_profile = ""
            if self.user_profile:
                # 최신 20개 정도만 가져와서 컨텍스트로 제공
                facts = self.user_profile.get_all_facts()
                sorted_facts = sorted(facts, key=lambda x: x.timestamp, reverse=True)[:20]
                if sorted_facts:
                    current_profile = "현재 알고 있는 마스터 정보:\n" + "\n".join([f"- {f.content}" for f in sorted_facts])
            
            # 요약 + 정보 추출 프롬프트 (시간 정보 강조)
            summarize_prompt = f"""다음 대화를 요약하고, 마스터에 대한 새로운 정보를 추출해주세요.

{current_profile}

대화 시간: {time_range}

대화:
{conversation_text}

다음 형식으로 답변해주세요:

[요약]
**반드시 시간 정보를 포함**하여 요약해주세요 (2-3문장):
- 언제 (날짜/시간대)
- 무슨 일이 있었는지
- 대화 중 시간이 흐른 경우 시간 흐름 반영

예시: "2월 8일 저녁 9시경, 마스터가 새 프로젝트에 대해 질문했습니다. 10시쯤 구체적인 구현 방법에 대해 논의했습니다."

[마스터 정보]
- 위 '현재 알고 있는 마스터 정보'에 없는 완전히 새로운 사실만 나열하세요.
- 기존 정보와 의미가 겹치거나 포함 관계라면 절대 적지 마세요.
- 기존 정보와 모순되거나 변경된 경우에만 적으세요.
- 해당 사항이 없으면 "없음"이라고 적어주세요.
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
    
    def _parse_response(self, response_text: str) -> Tuple[str, str, str, List[Dict]]:
        """
        응답 텍스트에서 감정 태그, 일본어, 일정 추출
        
        Args:
            response_text: AI 응답 텍스트
            
        Returns:
            (텍스트, 감정, 일본어, 이벤트 리스트) 튜플
        """
        # [이벤트] 태그 추출 및 제거
        events = []
        event_pattern = r'\[이벤트:([^\]]+)\]'
        event_matches = re.findall(event_pattern, response_text)
        
        for match in event_matches:
            # 형식: [이벤트:2026-03-15|병원 예약|오후 2시 치과]
            parts = [p.strip() for p in match.split('|')]
            if len(parts) >= 2:
                events.append({
                    'date': parts[0],
                    'title': parts[1],
                    'description': parts[2] if len(parts) > 2 else ""
                })
                print(f"[LLM] 일정 추출: {parts[0]} - {parts[1]}")
        
        # 이벤트 태그 제거
        response_text = re.sub(event_pattern, '', response_text)
        
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
        
        # 일본어 추출 및 제거
        japanese_text = None
        lines = clean_text.split('\n')
        
        # 역순으로 검사하여 일본어 줄 모두 찾기
        japanese_lines = []
        korean_lines = []
        
        for line in reversed(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            
            # 일본어인지 확인
            if self._is_japanese(line_stripped):
                japanese_lines.insert(0, line_stripped)
            else:
                # 일본어가 아닌 줄을 만나면 중단 (일본어는 끝에만 있다고 가정)
                break
        
        # 일본어 줄 제거하고 한국어만 남기기
        if japanese_lines:
            # 일본어 줄 수만큼 뒤에서 제거
            korean_lines = lines[:-len(japanese_lines)]
            # 첫 번째 일본어 줄만 TTS용으로 사용
            japanese_text = japanese_lines[0]
            # 한국어 텍스트 재구성
            clean_text = '\n'.join(korean_lines).strip()
        
        return clean_text, emotion, japanese_text, events
    
    def _is_japanese(self, text: str) -> bool:
        """일본어 텍스트인지 확인"""
        # 히라가나, 카타카나, 한자 유니코드 범위
        japanese_ranges = [
            (0x3040, 0x309F),  # Hiragana
            (0x30A0, 0x30FF),  # Katakana
            (0x4E00, 0x9FFF),  # CJK Unified Ideographs
        ]
        
        japanese_chars = 0
        for char in text:
            code = ord(char)
            for start, end in japanese_ranges:
                if start <= code <= end:
                    japanese_chars += 1
                    break
        
        # 텍스트의 20% 이상이 일본어 문자면 일본어로 판단
        return japanese_chars / len(text) > 0.2 if len(text) > 0 else False
    
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
