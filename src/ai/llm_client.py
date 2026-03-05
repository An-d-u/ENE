"""
Gemini LLM 클라이언트 (google-genai SDK 사용)
"""
import re
from typing import Tuple, List, Dict
from google import genai

from .prompt import get_system_prompt, get_available_emotions


class GeminiClient:
    """Gemini API 클라이언트"""
    
    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3-flash-preview",
        generation_params: dict | None = None,
        memory_manager=None,
        user_profile=None,
        settings=None,
        calendar_manager=None,
        mood_manager=None,
    ):
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
        self.model_name = model_name
        self.generation_params = self._normalize_generation_params(generation_params)
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        
        # Chat 세션 생성
        self.chat = self._create_chat_session()
        
        print(f"[LLM] Chat session created with model: {self.model_name}")
        if self.memory_manager:
            print("[LLM] Memory manager connected")

    def _create_chat_session(self, history=None):
        """Gemini chat 세션을 생성한다."""
        kwargs = {
            "model": self.model_name,
            "config": self._build_chat_config(include_sub_prompt=True),
        }
        if history is not None:
            kwargs["history"] = history
        return self.client.chats.create(**kwargs)

    def _normalize_generation_params(self, params: dict | None) -> dict:
        defaults = {
            "temperature": 0.9,
            "top_p": 1.0,
            "max_tokens": 2048,
        }
        if not isinstance(params, dict):
            return defaults

        normalized = dict(defaults)
        try:
            normalized["temperature"] = max(0.0, min(2.0, float(params.get("temperature", defaults["temperature"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["top_p"] = max(0.0, min(1.0, float(params.get("top_p", defaults["top_p"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["max_tokens"] = max(0, int(params.get("max_tokens", defaults["max_tokens"])))
        except (TypeError, ValueError):
            pass
        return normalized

    def _build_chat_config(self, include_sub_prompt: bool = True) -> dict:
        config = {
            "system_instruction": get_system_prompt(include_sub_prompt=include_sub_prompt),
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            config["max_output_tokens"] = self.generation_params["max_tokens"]
        return config

    def _generate_one_shot_text(self, message: str, include_sub_prompt: bool) -> str:
        """히스토리를 남기지 않는 일회성 생성 호출."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=message,
            config=self._build_chat_config(include_sub_prompt=include_sub_prompt),
        )
        return (response.text or "").strip()

    async def generate_markdown_document(self, message: str) -> str:
        """sub prompt 없이 마크다운 문서를 생성한다."""
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        diary_prompt = (
            "아래 요청에 맞춰 마크다운 문서를 작성하세요.\n"
            "- 출력은 마크다운 본문만 작성하세요.\n"
            "- 감정 태그, 일본어 번역, 부가 설명은 절대 포함하지 마세요.\n"
            "- 요청의 목적에 맞는 제목/본문 구조를 자연스럽게 구성하세요.\n\n"
            f"{enhanced}"
        )
        return self._generate_one_shot_text(diary_prompt, include_sub_prompt=False)

    async def generate_diary_completion_reply(self, context_message: str) -> Tuple[str, str, str, List[Dict]]:
        """파일 작성 완료 안내 응답을 생성한다."""
        response_text = self._generate_one_shot_text(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

    async def generate_note_command_plan(self, context_message: str) -> str:
        """sub prompt 없이 /note 실행 계획(Markdown)을 생성한다."""
        memory_context = await self._build_memory_context(context_message)
        enhanced = f"{memory_context}\n\n{context_message}" if memory_context else context_message
        return self._generate_one_shot_text(enhanced, include_sub_prompt=False)

    async def generate_note_execution_report(self, context_message: str) -> Tuple[str, str, str, List[Dict]]:
        """sub prompt 적용 상태로 /note 실행 결과 보고 응답을 생성한다."""
        response_text = self._generate_one_shot_text(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

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
            
            print(f"[LLM] Gemini 멀티모달 요청 전송...")
            response = self.chat.send_message(contents)
            self._log_turn_token_usage(response, label="멀티모달")
            
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
        if self.user_profile:
            profile_lines = ["[마스터 기본 정보]"]
            
            basic = getattr(self.user_profile, "basic_info", {}) or {}
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
            prefs = getattr(self.user_profile, "preferences", {}) or {}
            if prefs.get('likes'):
                profile_lines.append(f"- 좋아하는 것: {', '.join(prefs['likes'])}")
            
            if len(profile_lines) > 1:  # 정보가 있으면
                context_parts.append("\n".join(profile_lines))
                print(f"[LLM] 프로필 정보 포함: {len(profile_lines)-1}개 항목")

            # facts 전체를 컨텍스트에 포함
            if hasattr(self.user_profile, "get_all_facts"):
                facts = self.user_profile.get_all_facts()
                if facts:
                    fact_lines = ["[마스터에 대한 정보]"]
                    for fact in facts:
                        fact_lines.append(f"- [{fact.category}] : {fact.content}")
                    context_parts.append("\n".join(fact_lines))
                    print(f"[LLM] facts 포함: {len(facts)}개 항목")
        
        # 설정값 가져오기
        if self.mood_manager and hasattr(self.mood_manager, "build_context_block"):
            try:
                mood_block = self.mood_manager.build_context_block()
                if mood_block:
                    context_parts.append("\n" + mood_block)
                    print("[LLM] Mood context included")
            except Exception as e:
                print(f"[LLM] Mood context append failed: {e}")

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
        if recent_memories:
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

        # 6. 오늘 쓰다듬기 횟수 추가
        if self.calendar_manager:
            from datetime import datetime

            today_str = datetime.now().strftime("%Y-%m-%d")
            head_pat_count = self.calendar_manager.get_head_pat_count(today_str)
            context_parts.append("\n[오늘 상호작용]")
            context_parts.append(f"- 쓰다듬기: {head_pat_count}회")
        
        # 컨텍스트 문자열 생성
        if context_parts:
            result = "\n".join(context_parts)
            print(f"[LLM] 총 메모리 컨텍스트: {len(result)}자")
            return result
        
        print("[LLM] 사용 가능한 기억 없음")
        return ""
    
    def _log_turn_token_usage(self, response, label: str = "텍스트"):
        """응답 메타데이터에서 1회 입력/출력 토큰 사용량을 로깅한다."""
        def _read_field(container, *names):
            if container is None:
                return None
            for name in names:
                if hasattr(container, name):
                    value = getattr(container, name)
                    if value is not None:
                        return value
                if isinstance(container, dict) and name in container:
                    value = container.get(name)
                    if value is not None:
                        return value
            return None

        usage = None
        if hasattr(response, "usage_metadata"):
            usage = getattr(response, "usage_metadata")
        elif isinstance(response, dict):
            usage = response.get("usage_metadata")

        input_tokens = _read_field(
            usage,
            "prompt_token_count",
            "input_token_count",
            "prompt_tokens",
            "input_tokens",
        )
        output_tokens = _read_field(
            usage,
            "candidates_token_count",
            "output_token_count",
            "completion_token_count",
            "output_tokens",
            "completion_tokens",
        )
        total_tokens = _read_field(usage, "total_token_count", "total_tokens")

        in_str = str(input_tokens) if isinstance(input_tokens, int) else "N/A"
        out_str = str(output_tokens) if isinstance(output_tokens, int) else "N/A"
        total_str = str(total_tokens) if isinstance(total_tokens, int) else "N/A"
        print(f"[LLM] 🎫 Token Usage ({label}) | input={in_str}, output={out_str}, total={total_str}")

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
            self._log_turn_token_usage(response, label="텍스트")
            
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

            # 첫 대화~마지막 대화의 경과 시간 계산
            elapsed_hint = ""
            elapsed_minutes = 0
            if first_time and last_time:
                try:
                    start_dt = datetime.strptime(first_time, "%Y-%m-%d %H:%M")
                    end_dt = datetime.strptime(last_time, "%Y-%m-%d %H:%M")
                    delta = end_dt - start_dt
                    total_minutes = int(delta.total_seconds() // 60)
                    if total_minutes < 0:
                        total_minutes = 0
                    elapsed_minutes = total_minutes
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    if hours > 0 and minutes > 0:
                        elapsed_hint = f"{hours}시간 {minutes}분"
                    elif hours > 0:
                        elapsed_hint = f"{hours}시간"
                    else:
                        elapsed_hint = f"{minutes}분"
                except Exception:
                    elapsed_hint = ""
                    elapsed_minutes = 0

            # 현재 user_profile 스냅샷(기본정보/선호/기존 facts) 가져오기
            current_profile = ""
            if self.user_profile:
                profile_lines = ["현재 user_profile 스냅샷 (중복 금지 기준):"]

                # basic_info 포함
                if hasattr(self.user_profile, "basic_info"):
                    basic = self.user_profile.basic_info or {}
                    basic_lines = []
                    if basic.get("name"):
                        basic_lines.append(f"- 이름: {basic['name']}")
                    if basic.get("gender"):
                        basic_lines.append(f"- 성별: {basic['gender']}")
                    if basic.get("birthday"):
                        basic_lines.append(f"- 생일: {basic['birthday']}")
                    if basic.get("occupation"):
                        basic_lines.append(f"- 직업: {basic['occupation']}")
                    if basic.get("major"):
                        basic_lines.append(f"- 전공: {basic['major']}")
                    if basic_lines:
                        profile_lines.append("[basic_info]")
                        profile_lines.extend(basic_lines)

                # preferences 포함
                if hasattr(self.user_profile, "preferences"):
                    prefs = self.user_profile.preferences or {}
                    likes = prefs.get("likes", [])
                    dislikes = prefs.get("dislikes", [])
                    if likes or dislikes:
                        profile_lines.append("[preferences]")
                        if likes:
                            profile_lines.append(f"- likes: {', '.join(likes)}")
                        if dislikes:
                            profile_lines.append(f"- dislikes: {', '.join(dislikes)}")

                # 최신 facts 포함
                if hasattr(self.user_profile, "get_all_facts"):
                    facts = self.user_profile.get_all_facts()
                    sorted_facts = sorted(facts, key=lambda x: x.timestamp, reverse=True)[:20]
                    if sorted_facts:
                        profile_lines.append("[facts]")
                        profile_lines.extend([f"- [{f.category}] {f.content}" for f in sorted_facts])

                if len(profile_lines) > 1:
                    current_profile = "\n".join(profile_lines)
            
            # 요약 + 정보 추출 프롬프트 (시간 정보 강조)
            summarize_prompt = f"""아래 대화를 요약하고, 마스터 정보를 추출하세요.
[CURRENT_PROFILE]
{current_profile}

[TIME_RANGE]
{time_range}

[ELAPSED_HINT]
{elapsed_hint}

[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- {time_str}에 이루어진 대화 요약
- [CONVERSATION]의 타임스탬프를 우선 기준으로 각 시간 흐름을 요약하세요.
- 문장 수를 기계적으로 고정하지 말고, 자연스럽고 읽기 좋은 길이(보통 1~3문장)로 작성하세요.
- [TIME_RANGE]와 [ELAPSED_HINT]는 참고용이며, 그대로 복붙하지 말고 맥락에 맞게 표현하세요.
- 같은 사건을 반복하지 말고, 핵심 행동만 요약하세요.
- 예 : "2026년 2월 9일 오후 5시경, 마스터가 생굴을 먹고 노로바이러스에 걸려 고통을 호소하며 에네와 증상 및 식단에 대해 대화를 나눴습니다. 오후 6시 30분 무렵에는 직접 찍은 도트 이미지를 공유하며 무료함을 달랬고, 오후 9시 20분경부터는 미연시 게임을 플레이하며 등장인물의 외모에 대해 에네와 실랑이를 벌였습니다."

[MASTER_INFO]
- 없으면: none
- 있으면 아래 형식으로만 작성:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...

[ALLOW]
- basic: 신상/직업/학력/환경/관계 같은 정적 정보
- preference: 선호하는 방식이나 취향/스타일
- goal: 달성하려는 목표
- habit: 반복되는 행동/루틴 성향

[DISALLOW]
- 감정/기분/피곤함/흥분 등 일시적 상태
- 단순 인사/추임새
- 이미 basic 정보와 중복되는 취업/전공 진술
- 근거 없는 추측성 정보

[DEDUP]
- 기존 정보와 의미가 같으면 새로 쓰지 마세요.
- 같은 의미의 문장은 더 구체적인 1개만 남기세요.

[STYLE]
- 너무 길지 않게 간결하게 작성하세요.
- 출력 형식을 정확히 지키세요.
- "**"와 같은 강조표시의 사용은 금지합니다.
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

            # 요약에 날짜 정보가 없으면 최소한 시간 범위를 보강
            has_date = (
                re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", summary) is not None
                or re.search(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일", summary) is not None
            )
            if not has_date:
                summary = f"[{time_range}] {summary}".strip()
            
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
        """요약 응답 파싱 ([SUMMARY]와 [MASTER_INFO] 분리)."""
        summary_lines: list[str] = []
        user_facts: list[str] = []

        try:
            lines = response_text.split("\n")
            current_section = None

            for raw in lines:
                line = raw.strip()
                if not line:
                    continue

                upper = line.upper()
                # 섹션 헤더 감지: ASCII 토큰 + 구형 출력 호환
                if upper in {"[SUMMARY]", "SUMMARY"} or "[요약]" in line:
                    current_section = "summary"
                    continue
                if (
                    upper in {"[MASTER_INFO]", "MASTER_INFO"}
                    or "[마스터 정보]" in line
                    or "[사용자 정보]" in line
                    or "MASTER INFO" in upper
                ):
                    current_section = "facts"
                    continue

                if current_section == "summary":
                    # 사실 라인 형태는 summary에 섞이지 않게 제외
                    if re.match(r"^-\s*\[(basic|preference|goal|habit)\]\s*.+$", line, re.IGNORECASE):
                        continue
                    if line.startswith("-"):
                        line = line[1:].strip()
                    summary_lines.append(line)
                    continue

                if current_section == "facts":
                    if not line.startswith("-"):
                        continue
                    fact_line = line[1:].strip()
                    if not fact_line:
                        continue
                    if fact_line.lower() in {"none", "none.", "없음"}:
                        continue

                    tagged = re.match(r"^\[(basic|preference|goal|habit)\]\s*(.+)$", fact_line, re.IGNORECASE)
                    if tagged:
                        category = tagged.group(1).lower()
                        content = tagged.group(2).strip()
                        if content:
                            user_facts.append(f"[{category}] {content}")
                    else:
                        # 구형 형식도 최소 호환
                        user_facts.append(fact_line)

            summary = " ".join(summary_lines).strip()
            summary = re.sub(r"\s+", " ", summary).strip()
            if not summary:
                # fallback: 섹션 파싱 실패 시 상단 2줄만 요약으로 사용
                non_empty = [ln.strip() for ln in response_text.split("\n") if ln.strip()]
                summary = " ".join(non_empty[:2]).strip()

        except Exception as e:
            print(f"[LLM] 요약 파싱 실패: {e}")
            non_empty = [ln.strip() for ln in response_text.split("\n") if ln.strip()]
            summary = " ".join(non_empty[:2]).strip()
            user_facts = []

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
            # 일본어 줄 전체를 TTS용으로 사용 (여러 줄 허용)
            japanese_text = '\n'.join(japanese_lines).strip()
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
        self.chat = self._create_chat_session()
        print("[LLM] Chat session reset")

    def _get_item_role(self, item) -> str:
        """히스토리 아이템에서 role 값을 안전하게 추출한다."""
        if item is None:
            return ""
        if isinstance(item, dict):
            return str(item.get("role", "")).lower()
        role = getattr(item, "role", "")
        return str(role).lower()

    def rollback_last_assistant_turn(self) -> bool:
        """
        리롤 직전 턴(user+assistant)을 롤백한 히스토리로 chat 세션을 재구성한다.
        끝부분이 [user, model] 형태일 때만 안전하게 롤백하고,
        모호한 히스토리 구조에서는 실패로 반환해 리롤을 중단하게 한다.
        """
        history = self.get_conversation_history()
        if not history:
            print("[LLM] rollback skipped: history empty")
            return False

        trimmed_history = list(history)
        if not trimmed_history:
            print("[LLM] rollback skipped: history conversion failed")
            return False

        # 리롤은 마지막 assistant 응답 1개를 기준으로 동작하므로
        # 히스토리 tail이 반드시 model/assistant여야 한다.
        last_role = self._get_item_role(trimmed_history[-1])
        if last_role not in ("assistant", "model"):
            print(f"[LLM] rollback skipped: unexpected tail role '{last_role}'")
            return False

        # 마지막 assistant/model 제거
        trimmed_history.pop()

        # 직전 user 제거 (같은 user 입력 재전송 시 누적 방지)
        if not trimmed_history:
            print("[LLM] rollback skipped: missing user turn before assistant")
            return False
        last_user_role = self._get_item_role(trimmed_history[-1])
        if last_user_role != "user":
            print(f"[LLM] rollback skipped: expected user before assistant, got '{last_user_role}'")
            return False
        trimmed_history.pop()

        try:
            self.chat = self._create_chat_session(history=trimmed_history)
            print("[LLM] rollback_last_assistant_turn: success (user+assistant rolled back)")
            return True
        except Exception as e:
            print(f"[LLM] rollback_last_assistant_turn failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def rebuild_context_from_conversation(self, conversation_buffer: list) -> bool:
        """
        Bridge의 conversation_buffer를 기반으로 chat 세션을 재구성한다.
        SDK history 접근이 비어있는 환경에서 리롤 폴백 용도로 사용한다.
        """
        try:
            history = []
            for item in conversation_buffer or []:
                if not item or len(item) < 2:
                    continue
                role = str(item[0]).strip().lower()
                content = str(item[1]) if item[1] is not None else ""
                if role == "assistant":
                    role = "model"
                elif role != "user":
                    continue
                history.append({
                    "role": role,
                    "parts": [{"text": content}],
                })

            self.chat = self._create_chat_session(history=history)
            print(f"[LLM] rebuild_context_from_conversation: success ({len(history)} turns)")
            return True
        except Exception as e:
            print(f"[LLM] rebuild_context_from_conversation failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_conversation_history(self):
        """대화 내역 반환"""
        # Chat 세션에서 히스토리를 가져올 수 있다면 반환
        if hasattr(self.chat, 'history'):
            try:
                return list(self.chat.history)
            except Exception:
                return self.chat.history
        return []
