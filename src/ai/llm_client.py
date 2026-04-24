"""
Gemini LLM 클라이언트 (google-genai SDK 사용)
"""
import re
from typing import Tuple, List, Dict
from google import genai

from ..conversation_format import prepend_message_time
from .prompt import build_runtime_system_prompt, get_available_emotions
from .prompt_language import resolve_prompt_language
from .summary_prompt import build_markdown_document_prompt, build_summary_prompt

ANALYSIS_KEYS = {
    "user_emotion",
    "user_intent",
    "interaction_effect",
    "bond_delta_hint",
    "stress_delta_hint",
    "energy_delta_hint",
    "valence_delta_hint",
    "confidence",
    "flags",
}

SUMMARY_MEMORY_META_KEYS = {
    "memory_type",
    "importance_reason",
    "confidence",
    "entity_names",
}


class GeminiClient:
    """Gemini API 클라이언트"""
    
    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3-flash-preview",
        generation_params: dict | None = None,
        memory_manager=None,
        user_profile=None,
        ene_profile=None,
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
        self.ene_profile = ene_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self._last_token_usage = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
        
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
        system_instruction = build_runtime_system_prompt(
            include_sub_prompt=include_sub_prompt,
            include_analysis_appendix=True,
            settings_source=self.settings,
        )
        config = {
            "system_instruction": system_instruction,
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

    def _prompt_language(self) -> str:
        return resolve_prompt_language(settings_source=self.settings)

    def _memory_context_labels(self) -> dict[str, str]:
        language = resolve_prompt_language(settings_source=getattr(self, "settings", None))
        return {
            "ko": {
                "master_basic": "마스터 기본 정보",
                "master_facts": "마스터에 대한 정보",
                "ene_basic": "에네 기본 설정",
                "ene_facts": "에네에 대한 누적 정보",
                "important": "중요한 기억",
                "related": "관련된 과거 기억",
                "raw_chunks": "회상된 원문 조각",
                "chunk": "조각",
                "recent": "최근 대화 기록",
                "upcoming": "다가오는 일정",
                "activity": "최근 대화 활동",
                "interaction": "오늘 상호작용",
                "name": "이름",
                "gender": "성별",
                "birthday": "생일",
                "occupation": "직업",
                "major": "전공",
                "likes": "좋아하는 것",
                "done": "완료",
                "times": "회",
                "head_pat_today": "오늘 쓰다듬은 횟수",
                "head_pat_before": "메시지 전 쓰다듬은 횟수",
            },
            "en": {
                "master_basic": "Master Basic Information",
                "master_facts": "Information About Master",
                "ene_basic": "ENE Basic Settings",
                "ene_facts": "Accumulated Information About ENE",
                "important": "Important Memories",
                "related": "Related Past Memories",
                "raw_chunks": "Recalled Raw Text Chunks",
                "chunk": "Chunk",
                "recent": "Recent Conversation Records",
                "upcoming": "Upcoming Schedule",
                "activity": "Recent Conversation Activity",
                "interaction": "Today's Interaction",
                "name": "Name",
                "gender": "Gender",
                "birthday": "Birthday",
                "occupation": "Occupation",
                "major": "Major",
                "likes": "Likes",
                "done": "done",
                "times": "times",
                "head_pat_today": "Head pats today",
                "head_pat_before": "Head pats before this message",
            },
            "ja": {
                "master_basic": "マスター基本情報",
                "master_facts": "マスターに関する情報",
                "ene_basic": "エネ基本設定",
                "ene_facts": "エネに関する蓄積情報",
                "important": "重要な記憶",
                "related": "関連する過去の記憶",
                "raw_chunks": "思い出した原文断片",
                "chunk": "断片",
                "recent": "最近の会話記録",
                "upcoming": "今後の予定",
                "activity": "最近の会話活動",
                "interaction": "今日のやり取り",
                "name": "名前",
                "gender": "性別",
                "birthday": "誕生日",
                "occupation": "職業",
                "major": "専攻",
                "likes": "好きなもの",
                "done": "完了",
                "times": "回",
                "head_pat_today": "今日なでた回数",
                "head_pat_before": "メッセージ前になでた回数",
            },
        }[language]

    async def generate_markdown_document(self, message: str) -> str:
        """sub prompt 없이 마크다운 문서를 생성한다."""
        memory_context = await self._build_memory_context(message)
        diary_prompt = build_markdown_document_prompt(
            message,
            memory_context=memory_context,
            language=self._prompt_language(),
        )
        return self._generate_one_shot_text(diary_prompt, include_sub_prompt=False)

    async def generate_diary_completion_reply(
        self,
        context_message: str,
    ) -> Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict]]:
        """파일 작성 완료 안내 응답을 생성한다."""
        response_text = self._generate_one_shot_text(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

    async def generate_note_command_plan(self, context_message: str) -> str:
        """sub prompt 없이 /note 실행 계획(Markdown)을 생성한다."""
        memory_context = await self._build_memory_context(context_message)
        enhanced = f"{memory_context}\n\n{context_message}" if memory_context else context_message
        return self._generate_one_shot_text(enhanced, include_sub_prompt=False)

    async def generate_note_execution_report(
        self,
        context_message: str,
    ) -> Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict]]:
        """sub prompt 적용 상태로 /note 실행 결과 보고 응답을 생성한다."""
        response_text = self._generate_one_shot_text(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

    async def send_message_with_memory(
        self,
        message: str,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
    ) -> Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict]]:
        """
        메모리를 활용한 메시지 전송
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그, 일본어 번역, 이벤트 리스트) 튜플
        """
        # 메모리 컨텍스트 구성
        search_query = str(memory_search_text or "").strip() or message
        primary_query = str(latest_user_message or "").strip() or search_query
        support_context = str(recent_memory_context or "").strip()
        memory_context = await self._build_memory_context(
            primary_query,
            recent_context=support_context,
            head_pat_count_before_message=head_pat_count_before_message,
        )
        
        # 메모리가 있으면 메시지 앞에 추가
        if memory_context:
            enhanced_message = f"{memory_context}\n\n{message}"
            print(f"[LLM] 메모리 컨텍스트 추가 (길이: {len(memory_context)})")
        else:
            enhanced_message = message
        
        # 일반 메시지 전송
        return self.send_message(enhanced_message)
    
    async def send_message_with_images(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
    ) -> Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict]]:
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
                return await self.send_message_with_memory(
                    message,
                    memory_search_text,
                    latest_user_message,
                    recent_memory_context,
                    head_pat_count_before_message,
                )
            
            # 메모리 컨텍스트 추가
            search_query = str(memory_search_text or "").strip() or message
            primary_query = str(latest_user_message or "").strip() or search_query
            support_context = str(recent_memory_context or "").strip()
            memory_context = await self._build_memory_context(
                primary_query,
                recent_context=support_context,
                head_pat_count_before_message=head_pat_count_before_message,
            )
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
            clean_text, emotion, japanese_text, events, analysis, promises = self._parse_response(response_text)
            
            # 일본어가 있으면 로깅
            if japanese_text:
                print(f"[LLM] 일본어 번역: {japanese_text[:30]}...")
            
            # 일정이 있으면 로깅
            if events:
                print(f"[LLM] {len(events)}개 일정 추출됨")
            
            return clean_text, emotion, japanese_text, events, analysis, promises

            
        except Exception as e:
            print(f"[LLM] 멀티모달 처리 실패: {e}")
            import traceback
            traceback.print_exc()
            return f"이미지를 처리하는 중에 문제가 생겼어요... ({str(e)[:50]})", "confused", None, [], {}

    
    async def _build_memory_context(
        self,
        query: str,
        recent_context: str = "",
        head_pat_count_before_message: int | None = None,
    ) -> str:
        """
        메모리 기반 컨텍스트 구성
        
        Args:
            query: 사용자 쿼리
            recent_context: 최근 대화 보조 문맥
            
        Returns:
            컨텍스트 문자열
        """
        if not self.memory_manager:
            print("[LLM] 메모리 매니저 없음")
            return ""
        
        context_parts = []
        labels = GeminiClient._memory_context_labels(self)
        normalized_query = str(query or "").strip()
        normalized_recent_context = str(recent_context or "").strip()
        
        settings_config = self.settings.config if self.settings else {}
        max_profile_facts = settings_config.get("max_profile_facts_in_context", 10)
        try:
            max_profile_facts = max(0, int(max_profile_facts))
        except (TypeError, ValueError):
            max_profile_facts = 10

        # 0. 사용자 프로필 정보 (최우선)
        if self.user_profile:
            profile_lines = [f"[{labels['master_basic']}]"]
            
            basic = getattr(self.user_profile, "basic_info", {}) or {}
            if basic.get('name'):
                profile_lines.append(f"- {labels['name']}: {basic['name']}")
            if basic.get('gender'):
                profile_lines.append(f"- {labels['gender']}: {basic['gender']}")
            if basic.get('birthday'):
                profile_lines.append(f"- {labels['birthday']}: {basic['birthday']}")
            if basic.get('occupation'):
                profile_lines.append(f"- {labels['occupation']}: {basic['occupation']}")
            if basic.get('major'):
                profile_lines.append(f"- {labels['major']}: {basic['major']}")
            
            # 취미/선호도
            prefs = getattr(self.user_profile, "preferences", {}) or {}
            if prefs.get('likes'):
                profile_lines.append(f"- {labels['likes']}: {', '.join(prefs['likes'])}")
            
            if len(profile_lines) > 1:  # 정보가 있으면
                context_parts.append("\n".join(profile_lines))
                print(f"[LLM] 프로필 정보 포함: {len(profile_lines)-1}개 항목")

            # facts 전체를 컨텍스트에 포함
            if hasattr(self.user_profile, "get_all_facts"):
                facts = self.user_profile.get_all_facts()
                if facts:
                    try:
                        facts = sorted(
                            facts,
                            key=lambda fact: getattr(fact, "timestamp", "") or "",
                            reverse=True,
                        )
                    except Exception:
                        facts = list(facts)
                    if max_profile_facts > 0:
                        facts = facts[:max_profile_facts]
                    fact_lines = [f"[{labels['master_facts']}]"]
                    for fact in facts:
                        fact_lines.append(f"- [{fact.category}] : {fact.content}")
                    context_parts.append("\n".join(fact_lines))
                    print(f"[LLM] facts 포함: {len(facts)}개 항목")

        ene_profile = getattr(self, "ene_profile", None)
        if ene_profile:
            core_profile = getattr(ene_profile, "core_profile", {}) or {}
            ene_core_lines = [f"[{labels['ene_basic']}]"]
            for group_name in ("identity", "speaking_style", "relationship_tone"):
                values = core_profile.get(group_name, []) or []
                for value in values:
                    text = str(value or "").strip()
                    if text:
                        ene_core_lines.append(f"- {text}")
            if len(ene_core_lines) > 1:
                context_parts.append("\n".join(ene_core_lines))
                print(f"[LLM] 에네 기본 설정 포함: {len(ene_core_lines) - 1}개 항목")

            raw_ene_facts = list(getattr(ene_profile, "facts", []) or [])
            if raw_ene_facts:
                sorted_ene_facts = sorted(
                    raw_ene_facts,
                    key=lambda fact: (
                        0 if getattr(fact, "origin", "") == "manual" and not getattr(fact, "auto_update", True) else
                        1 if getattr(fact, "origin", "") == "manual" else
                        2,
                        str(getattr(fact, "timestamp", "") or ""),
                    ),
                )
                ene_fact_lines = [f"[{labels['ene_facts']}]"]
                for fact in sorted_ene_facts[:max_profile_facts]:
                    category = str(getattr(fact, "category", "") or "").strip()
                    content = str(getattr(fact, "content", "") or "").strip()
                    if not content:
                        continue
                    if category:
                        ene_fact_lines.append(f"- [{category}] {content}")
                    else:
                        ene_fact_lines.append(f"- {content}")
                if len(ene_fact_lines) > 1:
                    context_parts.append("\n".join(ene_fact_lines))
                    print(f"[LLM] 에네 facts 포함: {len(ene_fact_lines) - 1}개 항목")
        
        # 설정값 가져오기
        if self.mood_manager and hasattr(self.mood_manager, "build_context_block"):
            try:
                mood_block = self.mood_manager.build_context_block(
                    language=resolve_prompt_language(settings_source=getattr(self, "settings", None))
                )
                if mood_block:
                    context_parts.append("\n" + mood_block)
                    print("[LLM] Mood context included")
            except Exception as e:
                print(f"[LLM] Mood context append failed: {e}")

        max_important = settings_config.get('max_important_memories', 3)
        max_similar = settings_config.get('max_similar_memories', 3)
        min_sim = settings_config.get('min_similarity', 0.35)
        max_recent = settings_config.get('max_recent_memories', 2)
        max_raw_chunks = GeminiClient._normalize_int_setting(
            self,
            settings_config.get("max_raw_chunks_in_context", 2),
            default=2,
            min_value=0,
            max_value=5,
        )
        raw_chunk_turns = GeminiClient._normalize_int_setting(
            self,
            settings_config.get("raw_chunk_turns", 6),
            default=6,
            min_value=1,
            max_value=12,
        )
        
        # 1. 중요 기억 가져오기
        important_memories = self.memory_manager.get_important()
        if important_memories:
            print(f"[LLM] 중요 기억 {len(important_memories)}개 발견")
            context_parts.append(f"\n[{labels['important']}]")
            for memory in important_memories[:max_important]:
                context_parts.append(f"- {memory.summary}")
                print(f"  ⭐ {memory.summary[:50]}...")
        else:
            print("[LLM] 중요 기억 없음")
        
        similar_memories = []
        # 2. 유사 기억 검색
        try:
            similar_memories = await self.memory_manager.find_similar(
                normalized_query,
                top_k=max_similar,
                min_similarity=min_sim
            )
            
            if similar_memories:
                print(f"[LLM] 유사 기억 {len(similar_memories)}개 발견")
                context_parts.append(f"\n[{labels['related']}]")
                for memory, similarity in similar_memories:
                    context_parts.append(f"- {memory.summary}")
                    print(f"  [{similarity:.2f}] {memory.summary[:50]}...")
            else:
                print("[LLM] 유사 기억 없음")
        
        except Exception as e:
            print(f"[LLM] 유사 기억 검색 실패: {e}")
            import traceback
            traceback.print_exc()

        # 2.5. 유사 기억 안에서 raw chunk 회상
        if max_raw_chunks > 0 and similar_memories and hasattr(self.memory_manager, "find_relevant_raw_chunks"):
            try:
                raw_chunks = await self.memory_manager.find_relevant_raw_chunks(
                    normalized_query,
                    similar_memories,
                    recent_context=normalized_recent_context,
                    top_k=max_raw_chunks,
                    chunk_turns=raw_chunk_turns,
                )
                if raw_chunks:
                    print(f"[LLM] raw chunk {len(raw_chunks)}개 선택")
                    context_parts.append(f"\n[{labels['raw_chunks']}]")
                    for index, (chunk, score, score_meta) in enumerate(raw_chunks, start=1):
                        context_parts.append(
                            f"- {labels['chunk']} {index} (turn {chunk.start_turn_index}-{chunk.end_turn_index})"
                        )
                        for line in str(chunk.text or "").splitlines():
                            context_parts.append(f"  {line}")
                        print(
                            "[LLM] raw chunk 선택 "
                            f"{index}: score={score:.3f}, "
                            f"primary={score_meta.get('primary_similarity', 0.0):.3f}, "
                            f"support={score_meta.get('support_similarity', 0.0):.3f}, "
                            f"keyword={score_meta.get('keyword_score', 0.0):.3f}"
                        )
                else:
                    print("[LLM] raw chunk 없음")
            except Exception as e:
                print(f"[LLM] raw chunk 검색 실패: {e}")
                import traceback
                traceback.print_exc()
        
        # 3. 최근 기억도 추가 (임베딩 없어도 사용 가능)
        recent_memories = self.memory_manager.get_recent(count=max_recent)
        if recent_memories:
            print(f"[LLM] 최근 기억 {len(recent_memories)}개 사용")
            context_parts.append(f"[{labels['recent']}]")
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
                context_parts.append(f"\n[{labels['upcoming']}]")
                for event in upcoming:
                    try:
                        from datetime import datetime
                        event_date = datetime.fromisoformat(event.date)
                        date_str = event_date.strftime("%m월 %d일")
                        
                        # 완료 여부 표시
                        status = f" ✓ {labels['done']}" if event.completed else ""
                        
                        # 제목과 상세설명, 완료 상태를 한 줄로 표시
                        if event.description:
                            event_info = f"- {date_str}: {event.title} ({event.description}){status}"
                        else:
                            event_info = f"- {date_str}: {event.title}{status}"
                        
                        context_parts.append(event_info)
                        print(f"  📅 {event_info}")
                    except:
                        pass
        
        # 5. 최근 일주일 대화 횟수 추가 (없으면 전체 기록 중 가장 최근 1건 사용)
        if self.calendar_manager:
            recent_counts = self.calendar_manager.get_recent_or_latest_conversation_counts(days=7, exclude_today=True)
            if recent_counts:
                context_parts.append(f"\n[{labels['activity']}]")
                for date_str, count in recent_counts.items():
                    try:
                        from datetime import datetime
                        date_obj = datetime.fromisoformat(date_str)
                        date_display = date_obj.strftime("%m월 %d일")
                        context_parts.append(f"- {date_display}: {count}{labels['times']}")
                    except:
                        pass
                print(f"[LLM] 최근 대화 횟수 {len(recent_counts)}일 포함")

        # 6. 오늘 쓰다듬기 횟수 추가
        if self.calendar_manager:
            from datetime import datetime

            today_str = datetime.now().strftime("%Y-%m-%d")
            today_head_pat_count = int(self.calendar_manager.get_head_pat_count(today_str))
            if head_pat_count_before_message is None:
                head_pat_count = int(self.calendar_manager.get_pending_head_pat_count())
            else:
                head_pat_count = int(head_pat_count_before_message)
            context_parts.append(f"\n[{labels['interaction']}]")
            context_parts.append(f"- {labels['head_pat_today']}: {today_head_pat_count}{labels['times']}")
            context_parts.append(f"- {labels['head_pat_before']}: {head_pat_count}{labels['times']}")
        
        # 컨텍스트 문자열 생성
        if context_parts:
            result = "\n".join(context_parts)
            print(f"[LLM] 총 메모리 컨텍스트: {len(result)}자")
            return result
        
        print("[LLM] 사용 가능한 기억 없음")
        return ""

    def _normalize_int_setting(
        self,
        value,
        *,
        default: int,
        min_value: int,
        max_value: int,
    ) -> int:
        """정수 설정값을 안전하게 정규화한다."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, min(max_value, parsed))
    
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
        self._last_token_usage = {
            "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
            "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
            "total_tokens": total_tokens if isinstance(total_tokens, int) else None,
        }

        in_str = str(input_tokens) if isinstance(input_tokens, int) else "N/A"
        out_str = str(output_tokens) if isinstance(output_tokens, int) else "N/A"
        total_str = str(total_tokens) if isinstance(total_tokens, int) else "N/A"
        print(f"[LLM] 🎫 Token Usage ({label}) | input={in_str}, output={out_str}, total={total_str}")

    def get_last_token_usage(self) -> dict:
        """가장 최근 응답의 토큰 사용량 스냅샷을 반환한다."""
        usage = getattr(self, "_last_token_usage", None)
        if not isinstance(usage, dict):
            return {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            }
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }

    def send_message(
        self,
        message: str,
    ) -> Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict]]:
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
            text, emotion, japanese_text, events, analysis, promises = self._parse_response(response_text)
            
            # 일본어가 있으면 로깅
            if japanese_text:
                print(f"[LLM] 일본어 번역: {japanese_text[:30]}...")
            
            # 일정이 있으면 로깅
            if events:
                print(f"[LLM] {len(events)}개 일정 추출됨")
            
            return text, emotion, japanese_text, events, analysis, promises
            
        except Exception as e:
            print(f"[LLM] Error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def summarize_conversation(self, messages: list) -> tuple[str, list[str], list[str], dict]:
        """
        대화 내용 요약 및 사용자 정보 추출
        
        Args:
            messages: [(role, content), ...] 형식의 메시지 리스트
            
        Returns:
            (요약 텍스트, 사용자 정보 목록, 에네 정보 목록, 메모리 메타데이터) 튜플
        """
        try:
            summary_prompt = build_summary_prompt(
                messages,
                user_profile=self.user_profile,
                language=self._prompt_language(),
            )
            summarize_prompt = summary_prompt.prompt
            time_range = summary_prompt.time_range

            print(f"[LLM] 대화 요약 및 정보 추출 중... (메시지 수: {len(messages)})")
            
            # 일회성 요청으로 요약 생성 (Chat 세션과 별도)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=summarize_prompt,
                config={'temperature': 0.5}  # 요약은 더 일관성 있게
            )
            
            response_text = response.text.strip()
            
            # 응답 파싱
            summary, user_facts, ene_facts, memory_meta = self._parse_summary_response(response_text)

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
            if ene_facts:
                print(f"[LLM] 에네 정보 {len(ene_facts)}개 추출: {ene_facts}")
            if memory_meta:
                print(f"[LLM] 메모리 메타 추출: {memory_meta}")
            
            return summary, user_facts, ene_facts, memory_meta
            
        except Exception as e:
            print(f"[LLM] 요약 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            # 실패 시 간단한 요약 반환
            return f"대화 {len(messages)}개 메시지", [], [], {}
    
    def _parse_summary_memory_meta(self, meta_lines: list[str]) -> dict:
        """요약 응답의 MEMORY_META 섹션을 정규화된 딕셔너리로 파싱한다."""
        memory_meta: dict = {}

        for raw_line in meta_lines:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("-"):
                line = line[1:].strip()
            if not line or line.lower() in {"none", "none.", "없음"}:
                continue
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            normalized_key = key.strip().lower()
            if normalized_key not in SUMMARY_MEMORY_META_KEYS:
                continue

            normalized_value = value.strip()
            if not normalized_value:
                continue

            if normalized_key == "confidence":
                try:
                    memory_meta[normalized_key] = max(0.0, min(1.0, float(normalized_value)))
                except ValueError:
                    continue
                continue

            if normalized_key == "entity_names":
                cleaned_value = normalized_value.strip("[]")
                entity_names = [
                    item.strip().strip("'\"")
                    for item in cleaned_value.split(",")
                    if item.strip().strip("'\"")
                ]
                if entity_names:
                    memory_meta[normalized_key] = entity_names
                continue

            memory_meta[normalized_key] = normalized_value

        return memory_meta

    def _parse_summary_response(self, response_text: str) -> tuple[str, list[str], list[str], dict]:
        """요약 응답 파싱 ([SUMMARY], [MASTER_INFO], [ENE_INFO], [MEMORY_META] 분리)."""
        summary_lines: list[str] = []
        user_facts: list[str] = []
        ene_facts: list[str] = []
        memory_meta_lines: list[str] = []

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
                if upper in {"[ENE_INFO]", "ENE_INFO"} or "[에네 정보]" in line or "ENE INFO" in upper:
                    current_section = "ene_facts"
                    continue
                if upper in {"[MEMORY_META]", "MEMORY_META"} or "[기억 메타]" in line:
                    current_section = "memory_meta"
                    continue

                if current_section == "summary":
                    # 사실 라인 형태는 summary에 섞이지 않게 제외
                    if re.match(
                        r"^-\s*\[(basic|preference|goal|habit|speaking_style|relationship_tone)\]\s*.+$",
                        line,
                        re.IGNORECASE,
                    ):
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
                    continue

                if current_section == "ene_facts":
                    if not line.startswith("-"):
                        continue
                    fact_line = line[1:].strip()
                    if not fact_line:
                        continue
                    if fact_line.lower() in {"none", "none.", "없음"}:
                        continue

                    tagged = re.match(
                        r"^\[(basic|preference|goal|habit|speaking_style|relationship_tone)\]\s*(.+)$",
                        fact_line,
                        re.IGNORECASE,
                    )
                    if tagged:
                        category = tagged.group(1).lower()
                        content = tagged.group(2).strip()
                        if content:
                            ene_facts.append(f"[{category}] {content}")
                    else:
                        ene_facts.append(fact_line)
                    continue

                if current_section == "memory_meta":
                    memory_meta_lines.append(line)

            summary = " ".join(summary_lines).strip()
            summary = re.sub(r"\s+", " ", summary).strip()
            if not summary:
                # fallback: 섹션 파싱 실패 시 상단 2줄만 요약으로 사용
                non_empty = [ln.strip() for ln in response_text.split("\n") if ln.strip()]
                summary = " ".join(non_empty[:2]).strip()
            memory_meta = self._parse_summary_memory_meta(memory_meta_lines)

        except Exception as e:
            print(f"[LLM] 요약 파싱 실패: {e}")
            non_empty = [ln.strip() for ln in response_text.split("\n") if ln.strip()]
            summary = " ".join(non_empty[:2]).strip()
            user_facts = []
            ene_facts = []
            memory_meta = {}

        return summary, user_facts, ene_facts, memory_meta

    def _parse_analysis_lines(self, raw_block: str) -> Dict[str, str]:
        """analysis 메타 블록의 key=value 줄을 안전하게 파싱한다."""
        analysis: Dict[str, str] = {}
        for raw_line in raw_block.splitlines():
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in ANALYSIS_KEYS and value:
                analysis[key] = value
        return analysis

    def _extract_analysis_block(self, response_text: str) -> tuple[str, Dict[str, str]]:
        """응답의 analysis 블록 또는 상단 메타 줄을 분리해 구조화된 딕셔너리로 반환한다."""
        pattern = r"\[analysis\]\s*(.*?)\s*\[/analysis\]"
        match = re.search(pattern, response_text, re.IGNORECASE | re.DOTALL)
        if match:
            analysis = self._parse_analysis_lines(match.group(1))
            cleaned = re.sub(pattern, "", response_text, flags=re.IGNORECASE | re.DOTALL).strip()
            return cleaned, analysis

        lines = response_text.splitlines()
        prefix_lines = []
        consumed = 0
        seen_analysis_key = False
        started = False

        for index, raw_line in enumerate(lines):
            stripped = raw_line.strip()

            if not started and not stripped:
                consumed = index + 1
                continue

            if not stripped:
                if started and prefix_lines:
                    consumed = index + 1
                    break
                consumed = index + 1
                continue

            if "=" not in stripped:
                break

            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key not in ANALYSIS_KEYS or not value:
                break

            started = True
            seen_analysis_key = True
            prefix_lines.append(f"{key}={value}")
            consumed = index + 1

        if not seen_analysis_key:
            return response_text, {}

        analysis = self._parse_analysis_lines("\n".join(prefix_lines))
        cleaned = "\n".join(lines[consumed:]).strip()
        return cleaned, analysis

    def _extract_japanese_lines(self, text: str) -> tuple[str, str | None]:
        """본문 어디에 있든 일본어 전용 줄을 분리해 표시용 텍스트에서 제거한다."""
        visible_lines = []
        japanese_lines = []

        for raw_line in text.split("\n"):
            stripped = raw_line.strip()
            if not stripped:
                visible_lines.append("")
                continue

            if self._is_japanese(stripped):
                japanese_lines.append(stripped)
                continue

            visible_lines.append(raw_line.rstrip())

        clean_text = "\n".join(visible_lines).strip()
        japanese_text = "\n".join(japanese_lines).strip() if japanese_lines else None
        return clean_text, japanese_text

    def _parse_response(self, response_text: str) -> Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict]]:
        """
        응답 텍스트에서 감정 태그, 일본어, 일정 추출
        
        Args:
            response_text: AI 응답 텍스트
            
        Returns:
            (텍스트, 감정, 일본어, 이벤트 리스트, analysis 메타, 약속 리스트) 튜플
        """
        response_text, analysis = self._extract_analysis_block(response_text)

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

        promises = []
        promise_pattern = r'\[약속:([^\]]+)\]'
        promise_matches = re.findall(promise_pattern, response_text)
        for match in promise_matches:
            parts = [p.strip() for p in match.split('|')]
            if len(parts) >= 2:
                promises.append({
                    'trigger_at': parts[0],
                    'title': parts[1],
                    'source': parts[2] if len(parts) > 2 else "user",
                    'source_excerpt': parts[3] if len(parts) > 3 else "",
                })

        response_text = re.sub(promise_pattern, '', response_text)
        
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
        clean_text, japanese_text = self._extract_japanese_lines(clean_text)

        return clean_text, emotion, japanese_text, events, analysis, promises
    
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
                raw_content = str(item[1]) if item[1] is not None else ""
                timestamp = str(item[2]).strip() if len(item) >= 3 and item[2] else ""
                content = prepend_message_time(raw_content, timestamp)
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
