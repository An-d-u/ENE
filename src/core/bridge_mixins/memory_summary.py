"""
WebBridge의 대화 요약과 장기기억 저장 흐름을 담당한다.
"""
import json
import inspect
from datetime import datetime
import re
import uuid

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot


class SummaryReviewWorker(QThread):
    """수동 대화 요약 후보 생성을 UI 스레드 밖에서 실행한다."""

    prepared = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, bridge, messages):
        super().__init__()
        self.bridge = bridge
        self.messages = list(messages or [])
        self._cancellation_requested = False

    def requestInterruption(self) -> None:
        """스레드 시작 전 취소 요청도 잃지 않도록 함께 기록한다."""
        self._cancellation_requested = True
        super().requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancellation_requested or self.isInterruptionRequested()

    def run(self):
        import asyncio

        loop = None
        try:
            if self._is_cancelled():
                return
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            builder = getattr(self.bridge, "_build_summary_review_state", None)
            if not callable(builder):
                builder = lambda messages: MemorySummaryBridgeMixin._build_summary_review_state(
                    self.bridge,
                    messages,
                )
            pending = loop.run_until_complete(builder(self.messages))
            if self._is_cancelled():
                return
            self.prepared.emit(pending)
        except BaseException:
            if self._is_cancelled():
                return
            self.failed.emit("summary_review_error")
        finally:
            asyncio.set_event_loop(None)
            if loop is not None:
                loop.close()


class MemorySummaryBridgeMixin:
    @staticmethod
    def _summary_bridge_is_shutting_down(bridge) -> bool:
        state = getattr(bridge, "life_record_state", None)
        return getattr(state, "phase", None) == "shutting_down"

    def _loaded_topic_memory_context_for_messages(self, messages) -> str:
        """이번 요약 범위에서 응답 생성 때 실제로 로드된 주제 기억만 모은다."""
        reviewed_count = len(list(messages or []))
        if reviewed_count <= 0:
            return ""

        entries = getattr(self, "_loaded_topic_memory_context_buffer", []) or []
        collected: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                conversation_index = int(entry.get("conversation_index", -1))
            except Exception:
                conversation_index = -1
            if conversation_index < 0 or conversation_index >= reviewed_count:
                continue
            context = str(entry.get("context") or "").strip()
            if not context or context in seen:
                continue
            seen.add(context)
            collected.append(context)
        return "\n".join(collected)

    async def _summarize_conversation_with_loaded_topic_memory(self, messages):
        """지원되는 클라이언트에는 loaded topic memory 비교 컨텍스트를 함께 전달한다."""
        context_builder = getattr(self, "_loaded_topic_memory_context_for_messages", None)
        if not callable(context_builder):
            context_builder = lambda value: MemorySummaryBridgeMixin._loaded_topic_memory_context_for_messages(
                self,
                value,
            )
        loaded_context = context_builder(messages)
        summarize = getattr(self.llm_client, "summarize_conversation")
        if loaded_context:
            supports_loaded_context = False
            try:
                signature = inspect.signature(summarize)
                supports_loaded_context = (
                    "loaded_topic_memory_context" in signature.parameters
                    or any(
                        parameter.kind == inspect.Parameter.VAR_KEYWORD
                        for parameter in signature.parameters.values()
                    )
                )
            except (TypeError, ValueError):
                supports_loaded_context = False
            if supports_loaded_context:
                return await summarize(messages, loaded_topic_memory_context=loaded_context)
        return await summarize(messages)

    def _create_memory_conversation_id(self, messages) -> str:
        """현재 요약 대상 대화를 식별할 안정적인 ID를 만든다."""
        latest_timestamp = ""
        if messages:
            last_item = messages[-1]
            if len(last_item) >= 3 and last_item[2]:
                latest_timestamp = str(last_item[2]).strip()
        if not latest_timestamp:
            latest_timestamp = self._now_timestamp()
        compact = re.sub(r"[^0-9]", "", latest_timestamp)[:12] or datetime.now().strftime("%Y%m%d%H%M")
        return f"conv-{compact}-{uuid.uuid4().hex[:8]}"

    @pyqtSlot()
    def summarize_now(self):
        """UI에서 호출: 현재 대화를 즉시 요약해 메모리에 저장."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] Manual summarize ignored: worker is still running")
            self.summary_notice.emit("응답 생성 중에는 요약할 수 없어요.", "error")
            return

        if not self.llm_client or not self.memory_manager:
            print("[Bridge] Manual summarize ignored: llm/memory not initialized")
            self.summary_notice.emit("요약 기능이 아직 준비되지 않았어요.", "error")
            return

        if not self.conversation_buffer:
            print("[Bridge] Manual summarize ignored: no conversation to summarize")
            self.summary_notice.emit("요약할 대화가 없어요.", "info")
            return

        starter = getattr(self, "_start_summary_review_worker", None)
        if not callable(starter):
            starter = lambda messages, success_notice=None: MemorySummaryBridgeMixin._start_summary_review_worker(
                self,
                messages,
                success_notice=success_notice,
            )
        starter(self.conversation_buffer.copy(), success_notice="요약을 확인해 주세요.")

    def _start_summary_review_worker(self, messages, *, success_notice: str):
        """요약 후보 생성을 별도 스레드에서 시작한다."""
        if MemorySummaryBridgeMixin._summary_bridge_is_shutting_down(self):
            return None
        current_worker = getattr(self, "_summary_review_worker", None)
        if current_worker is not None and current_worker.isRunning():
            print("[Bridge] Summary review ignored: worker is still running")
            self.summary_notice.emit("이미 요약을 만드는 중이에요.", "info")
            return current_worker

        worker = SummaryReviewWorker(self, messages)
        self._summary_review_worker = worker
        self._summary_review_success_notice = success_notice
        prepared_handler = getattr(self, "_on_summary_review_prepared", None)
        if not callable(prepared_handler):
            prepared_handler = lambda pending: MemorySummaryBridgeMixin._on_summary_review_prepared(self, pending)
        failed_handler = getattr(self, "_on_summary_review_failed", None)
        if not callable(failed_handler):
            failed_handler = lambda error: MemorySummaryBridgeMixin._on_summary_review_failed(self, error)
        finished_handler = getattr(self, "_on_summary_review_worker_finished", None)
        if not callable(finished_handler):
            finished_handler = lambda value: MemorySummaryBridgeMixin._on_summary_review_worker_finished(self, value)

        worker.prepared.connect(prepared_handler)
        worker.failed.connect(failed_handler)
        worker.finished.connect(lambda: finished_handler(worker))
        worker.start()
        return worker

    def _on_summary_review_prepared(self, pending):
        if MemorySummaryBridgeMixin._summary_bridge_is_shutting_down(self):
            return
        if not isinstance(pending, dict):
            self.summary_notice.emit("요약할 대화가 없어요.", "info")
            return

        self._pending_summary_review = pending
        self._emit_summary_review()
        notice = getattr(self, "_summary_review_success_notice", "요약을 확인해 주세요.")
        self.summary_notice.emit(notice, "info")

    def _on_summary_review_failed(self, error: str):
        if MemorySummaryBridgeMixin._summary_bridge_is_shutting_down(self):
            return
        print("[Bridge] Manual summarize failed: summary_review_error")
        self.summary_notice.emit("요약 중 오류가 발생했어요.", "error")

    def _on_summary_review_worker_finished(self, worker):
        if MemorySummaryBridgeMixin._summary_bridge_is_shutting_down(self):
            return
        if getattr(self, "_summary_review_worker", None) is worker:
            self._summary_review_worker = None
        self._summary_review_success_notice = ""

    def _normalize_summary_result(self, summary_result):
        """LLM 요약 응답을 저장/검토에 쓰기 쉬운 형태로 정규화한다."""
        ene_facts = []
        topic_hints = []
        if isinstance(summary_result, tuple) and len(summary_result) == 5:
            summary, user_facts, ene_facts, memory_meta, topic_hints = summary_result
        elif isinstance(summary_result, tuple) and len(summary_result) == 4:
            summary, user_facts, ene_facts, memory_meta = summary_result
        elif isinstance(summary_result, tuple) and len(summary_result) == 3:
            summary, user_facts, memory_meta = summary_result
        elif isinstance(summary_result, tuple) and len(summary_result) == 2:
            summary, user_facts = summary_result
            memory_meta = {}
        else:
            raise ValueError("지원하지 않는 요약 응답 형식입니다.")

        if not isinstance(user_facts, list):
            user_facts = []
        if not isinstance(ene_facts, list):
            ene_facts = []
        if not isinstance(memory_meta, dict):
            memory_meta = {}

        topic_normalizer = getattr(self, "_normalize_topic_hints", None)
        if not callable(topic_normalizer):
            topic_normalizer = lambda hints: MemorySummaryBridgeMixin._normalize_topic_hints(self, hints)

        return (
            str(summary or "").strip(),
            user_facts,
            ene_facts,
            memory_meta,
            topic_normalizer(topic_hints),
        )

    def _normalize_topic_hints(self, topic_hints):
        """TOPIC_MEMORY 힌트를 UI payload에 넣을 수 있는 dict 목록으로 정규화한다."""
        normalized = []
        if not isinstance(topic_hints, list):
            return normalized

        allowed_keys = {
            "keyword",
            "subject",
            "type",
            "state",
            "text",
            "aliases",
            "retrieval_terms",
            "confidence",
        }
        list_keys = {"aliases", "retrieval_terms"}
        for hint in topic_hints:
            to_dict = getattr(hint, "to_dict", None)
            if callable(to_dict):
                raw = to_dict()
            elif isinstance(hint, dict):
                raw = hint
            else:
                continue
            if not isinstance(raw, dict):
                continue

            item = {}
            for key in allowed_keys:
                if key not in raw:
                    continue
                value = raw.get(key)
                if key in list_keys:
                    if isinstance(value, list):
                        item[key] = [str(part).strip() for part in value if str(part or "").strip()]
                    elif str(value or "").strip():
                        item[key] = [str(value).strip()]
                    else:
                        item[key] = []
                elif key == "confidence":
                    try:
                        item[key] = max(0.0, min(1.0, float(value)))
                    except (TypeError, ValueError):
                        item[key] = 0.5
                else:
                    item[key] = str(value or "").strip()
            if item:
                normalized.append(item)
        return normalized

    def _normalize_topic_hints_for_storage(self, topic_hints):
        """승인된 topic_hints 중 KnowledgeMapManager에 저장 가능한 항목만 남긴다."""
        try:
            from src.ai.knowledge_map_types import TopicMemoryHint
        except Exception as e:
            print(f"[Bridge] Topic hint type import failed: {e}")
            return []

        topic_normalizer = getattr(self, "_normalize_topic_hints", None)
        if not callable(topic_normalizer):
            topic_normalizer = lambda hints: MemorySummaryBridgeMixin._normalize_topic_hints(self, hints)

        normalized = topic_normalizer(topic_hints)
        storage_hints = []
        for item in normalized:
            if not isinstance(item, dict):
                continue
            try:
                hint = TopicMemoryHint.from_dict(item)
            except (TypeError, ValueError):
                continue
            if not hint.keyword or not hint.subject or not hint.type or not hint.state or not hint.text:
                continue
            storage_hints.append(hint.to_dict())
        return storage_hints

    def _reviewed_summary_source_memory_id(self, saved_memory, pending, source_timestamp):
        """지식 맵 단서가 어느 요약에서 왔는지 추적할 ID를 고른다."""
        memory_id = str(getattr(saved_memory, "id", "") or "").strip()
        if memory_id:
            return memory_id

        original_messages = list(pending.get("original_messages") or []) if isinstance(pending, dict) else []
        for message in original_messages:
            if not isinstance(message, dict):
                continue
            conversation_id = str(message.get("conversation_id") or "").strip()
            if conversation_id:
                return conversation_id
        return str(source_timestamp or "").strip()

    async def _persist_reviewed_topic_hints(self, topic_hints, saved_memory, pending, source_timestamp):
        """승인된 topic_hints만 지식 맵에 병합하고, 실패해도 요약 저장은 유지한다."""
        storage_normalizer = getattr(self, "_normalize_topic_hints_for_storage", None)
        if not callable(storage_normalizer):
            storage_normalizer = lambda hints: MemorySummaryBridgeMixin._normalize_topic_hints_for_storage(self, hints)
        storage_hints = storage_normalizer(topic_hints)
        if not storage_hints:
            return

        knowledge_map_manager = getattr(self, "knowledge_map_manager", None)
        if knowledge_map_manager is None:
            return

        source_builder = getattr(self, "_reviewed_summary_source_memory_id", None)
        if not callable(source_builder):
            source_builder = lambda memory, review, timestamp: MemorySummaryBridgeMixin._reviewed_summary_source_memory_id(
                self,
                memory,
                review,
                timestamp,
            )
        source_memory_id = source_builder(saved_memory, pending, source_timestamp)
        try:
            async_merge = getattr(knowledge_map_manager, "async_merge_hints", None)
            if callable(async_merge):
                merge_result = async_merge(storage_hints, source_memory_id=source_memory_id)
                if inspect.isawaitable(merge_result):
                    await merge_result
            else:
                merge_direct = getattr(knowledge_map_manager, "merge_hints_direct", None)
                if not callable(merge_direct):
                    merge_direct = getattr(knowledge_map_manager, "merge_hints", None)
                if not callable(merge_direct):
                    return
                merge_direct(storage_hints, source_memory_id=source_memory_id)

            save = getattr(knowledge_map_manager, "save", None)
            if callable(save):
                save()
        except Exception as e:
            print(f"[Bridge] Topic hints save skipped after failure: {e}")

    def _build_summary_storage_payload(self, messages):
        """요약 저장에 필요한 원문 메시지와 출처 시각을 만든다."""
        source_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        if messages and len(messages[-1]) == 3 and messages[-1][2]:
            source_timestamp = str(messages[-1][2]).strip()
        conversation_id_builder = getattr(self, "_create_memory_conversation_id", None)
        if callable(conversation_id_builder):
            conversation_id = conversation_id_builder(messages)
        else:
            conversation_id = MemorySummaryBridgeMixin._create_memory_conversation_id(self, messages)

        original_messages = []
        for turn_index, item in enumerate(messages):
            role = str(item[0] if len(item) >= 1 else "unknown").strip() or "unknown"
            text = str(item[1] if len(item) >= 2 else "").strip()
            timestamp = (
                str(item[2]).strip()
                if len(item) >= 3 and item[2]
                else source_timestamp
            )
            original_messages.append(
                {
                    "role": role,
                    "text": text,
                    "timestamp": timestamp,
                    "conversation_id": conversation_id,
                    "turn_index": turn_index,
                }
            )

        return {
            "source_timestamp": source_timestamp,
            "original_messages": original_messages,
        }

    def _emit_summary_review(self):
        """현재 대기 중인 수동 요약 검토 payload를 UI로 보낸다."""
        pending = getattr(self, "_pending_summary_review", None)
        if not isinstance(pending, dict):
            return

        payload = {
            "summary": str(pending.get("summary") or ""),
            "user_facts": list(pending.get("user_facts") or []),
            "ene_facts": list(pending.get("ene_facts") or []),
            "memory_meta": dict(pending.get("memory_meta") or {}),
            "topic_hints": list(pending.get("topic_hints") or []),
        }
        self.summary_review_ready.emit(json.dumps(payload, ensure_ascii=False))

    def _drop_reviewed_messages_from_buffer(self, reviewed_messages):
        """검토 대상으로 저장한 메시지만 버퍼에서 제거하고 이후 새 대화는 보존한다."""
        reviewed = list(reviewed_messages or [])
        if not reviewed:
            return

        current = list(getattr(self, "conversation_buffer", []) or [])
        reviewed_count = len(reviewed)
        if current[:reviewed_count] != reviewed:
            print("[Bridge] 요약 검토 중 대화 버퍼가 달라져 현재 버퍼를 유지합니다.")
            return

        self.conversation_buffer = current[reviewed_count:]
        loaded_topic_entries = getattr(self, "_loaded_topic_memory_context_buffer", None)
        if isinstance(loaded_topic_entries, list):
            kept_topic_entries = []
            for entry in loaded_topic_entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    conversation_index = int(entry.get("conversation_index", -1))
                except Exception:
                    conversation_index = -1
                if conversation_index >= reviewed_count:
                    updated = dict(entry)
                    updated["conversation_index"] = conversation_index - reviewed_count
                    kept_topic_entries.append(updated)
            self._loaded_topic_memory_context_buffer = kept_topic_entries
        thought_entries = getattr(self, "_ene_thought_context_buffer", None)
        if not isinstance(thought_entries, list):
            return
        if not self.conversation_buffer:
            self._ene_thought_context_buffer = []
            return

        kept = []
        for entry in thought_entries:
            if not isinstance(entry, dict):
                continue
            try:
                conversation_index = int(entry.get("conversation_index", -1))
            except Exception:
                conversation_index = -1
            if conversation_index >= reviewed_count:
                updated = dict(entry)
                updated["conversation_index"] = conversation_index - reviewed_count
                kept.append(updated)
        self._ene_thought_context_buffer = kept

    async def _build_summary_review_state(self, messages):
        """요약 후보 생성 결과를 검토 대기 상태 딕셔너리로 만든다."""
        summarizer = getattr(self, "_summarize_conversation_with_loaded_topic_memory", None)
        if not callable(summarizer):
            summarizer = lambda value: MemorySummaryBridgeMixin._summarize_conversation_with_loaded_topic_memory(
                self,
                value,
            )
        summary_result = await summarizer(messages)
        summary, user_facts, ene_facts, memory_meta, topic_hints = self._normalize_summary_result(summary_result)
        storage_builder = getattr(self, "_build_summary_storage_payload", None)
        if not callable(storage_builder):
            storage_builder = lambda value: MemorySummaryBridgeMixin._build_summary_storage_payload(self, value)
        storage_payload = storage_builder(messages)
        return {
            "messages": messages,
            "original_messages": storage_payload["original_messages"],
            "source_timestamp": storage_payload["source_timestamp"],
            "summary": summary,
            "user_facts": user_facts,
            "ene_facts": ene_facts,
            "memory_meta": memory_meta,
            "topic_hints": topic_hints,
        }

    async def _prepare_summary_review(self):
        """수동 요약 결과를 저장 전 검토 상태로 준비한다."""
        if not self.conversation_buffer or not self.memory_manager or not self.llm_client:
            return

        messages = self.conversation_buffer.copy()
        builder = getattr(self, "_build_summary_review_state", None)
        if not callable(builder):
            builder = lambda value: MemorySummaryBridgeMixin._build_summary_review_state(self, value)
        self._pending_summary_review = await builder(messages)
        self._emit_summary_review()

    async def _persist_reviewed_summary(self, summary, user_facts, ene_facts, memory_meta, topic_hints=None):
        """검토가 끝난 요약과 승인된 정보만 실제 저장소에 반영한다."""
        pending = getattr(self, "_pending_summary_review", None)
        if not isinstance(pending, dict):
            raise ValueError("저장할 요약 검토 항목이 없습니다.")

        if not isinstance(memory_meta, dict):
            memory_meta = {}
        if not isinstance(user_facts, list):
            user_facts = []
        if not isinstance(ene_facts, list):
            ene_facts = []

        source_timestamp = str(pending.get("source_timestamp") or datetime.now().strftime('%Y-%m-%d %H:%M'))
        original_messages = list(pending.get("original_messages") or [])

        saved_memory = await self.memory_manager.add_summary(
            summary=str(summary or "").strip(),
            original_messages=original_messages,
            is_important=False,
            source="chat",
            memory_type=str(memory_meta.get("memory_type") or "general"),
            importance_reason=str(memory_meta.get("importance_reason")).strip() if memory_meta.get("importance_reason") else None,
            confidence=memory_meta.get("confidence"),
            entity_names=memory_meta.get("entity_names") or [],
            aliases=memory_meta.get("aliases") or [],
            trigger_terms=memory_meta.get("trigger_terms") or [],
        )

        if user_facts and hasattr(self, 'user_profile') and self.user_profile:
            print(f"[Bridge] 마스터 정보 {len(user_facts)}개 저장")
            for fact in user_facts:
                self.user_profile.add_fact(
                    content=fact,
                    category="fact",
                    source=f"대화 요약 ({source_timestamp})"
                )

        if ene_facts and hasattr(self, 'ene_profile') and self.ene_profile:
            print(f"[Bridge] 에네 정보 {len(ene_facts)}개 저장")
            for fact in ene_facts:
                self.ene_profile.add_fact(
                    content=fact,
                    category="fact",
                    source=f"대화 요약 ({source_timestamp})",
                    origin="auto",
                    auto_update=True,
                )

        topic_persister = getattr(self, "_persist_reviewed_topic_hints", None)
        if not callable(topic_persister):
            topic_persister = lambda hints, memory, review, timestamp: MemorySummaryBridgeMixin._persist_reviewed_topic_hints(
                self,
                hints,
                memory,
                review,
                timestamp,
            )
        await topic_persister(topic_hints, saved_memory, pending, source_timestamp)

        clear_context = getattr(self.llm_client, "clear_context", None)
        if callable(clear_context):
            clear_context()
            print("[Bridge] 대화 요약 후 LLM 세션 컨텍스트 초기화")

        self._drop_reviewed_messages_from_buffer(pending.get("messages") or [])
        self._pending_summary_review = None

    @pyqtSlot(str)
    def approve_summary_review(self, payload_json: str):
        """JS에서 호출: 사용자가 검토한 요약을 저장한다."""
        import asyncio
        loop = None
        try:
            payload = json.loads(str(payload_json or "{}"))
            if not isinstance(payload, dict):
                payload = {}

            summary = str(payload.get("summary") or "").strip()
            if not summary:
                self.summary_notice.emit("요약 내용이 비어 있어 저장하지 않았어요.", "error")
                return

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self._persist_reviewed_summary(
                    summary,
                    payload.get("user_facts") or [],
                    payload.get("ene_facts") or [],
                    payload.get("memory_meta") or {},
                    payload.get("topic_hints") or [],
                )
            )
            self.summary_notice.emit("대화 요약을 저장했어요.", "success")
            saved_signal = getattr(self, "summary_review_saved", None)
            if saved_signal is not None:
                saved_signal.emit()
        except Exception as e:
            print(f"[Bridge] Summary review approve failed: {e}")
            import traceback
            traceback.print_exc()
            self.summary_notice.emit("요약 저장 중 오류가 발생했어요.", "error")
        finally:
            if loop is not None:
                loop.close()

    @pyqtSlot()
    def regenerate_summary_review(self):
        """JS에서 호출: 같은 원문으로 요약 후보를 다시 생성한다."""
        try:
            pending = getattr(self, "_pending_summary_review", None)
            if not isinstance(pending, dict):
                self.summary_notice.emit("다시 만들 요약이 없어요.", "error")
                return

            messages = list(pending.get("messages") or [])
            if not messages:
                self.summary_notice.emit("요약 원문이 없어 다시 만들 수 없어요.", "error")
                return

            starter = getattr(self, "_start_summary_review_worker", None)
            if not callable(starter):
                starter = lambda value, success_notice=None: MemorySummaryBridgeMixin._start_summary_review_worker(
                    self,
                    value,
                    success_notice=success_notice,
                )
            starter(messages, success_notice="요약을 다시 만들었어요.")
        except Exception as e:
            print(f"[Bridge] Summary review regenerate failed: {e}")
            import traceback
            traceback.print_exc()
            self.summary_notice.emit("요약 재생성 중 오류가 발생했어요.", "error")

    @pyqtSlot()
    def cancel_summary_review(self):
        """JS에서 호출: 수동 요약 검토를 취소한다."""
        self._pending_summary_review = None
        self.summary_notice.emit("요약 저장을 취소했어요.", "info")

    def _check_auto_summarize(self):
        """자동 요약 확인"""
        if not self.memory_manager:
            return

        if isinstance(getattr(self, "_pending_summary_review", None), dict):
            print("[Bridge] 수동 요약 검토 중이라 자동 요약을 미룹니다.")
            return

        threshold = max(0, int(getattr(self, "summarize_threshold", 10) or 0))
        if threshold == 0:
            return

        if len(self.conversation_buffer) >= threshold:
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
            
            # LLM으로 요약 + 사용자/에네 정보 생성
            summarizer = getattr(self, "_summarize_conversation_with_loaded_topic_memory", None)
            if not callable(summarizer):
                summarizer = lambda value: MemorySummaryBridgeMixin._summarize_conversation_with_loaded_topic_memory(
                    self,
                    value,
                )
            summary_result = await summarizer(messages)
            normalizer = getattr(self, "_normalize_summary_result", None)
            if not callable(normalizer):
                normalizer = lambda result: MemorySummaryBridgeMixin._normalize_summary_result(self, result)
            storage_builder = getattr(self, "_build_summary_storage_payload", None)
            if not callable(storage_builder):
                storage_builder = lambda value: MemorySummaryBridgeMixin._build_summary_storage_payload(self, value)

            summary, user_facts, ene_facts, memory_meta, _topic_hints = normalizer(summary_result)
            storage_payload = storage_builder(messages)
            source_timestamp = storage_payload["source_timestamp"]
            original_messages = storage_payload["original_messages"]
            
            # 메모리에 요약 저장
            await self.memory_manager.add_summary(
                summary=summary,
                original_messages=original_messages,
                is_important=False,
                source="chat",
                memory_type=str(memory_meta.get("memory_type") or "general"),
                importance_reason=str(memory_meta.get("importance_reason")).strip() if memory_meta.get("importance_reason") else None,
                confidence=memory_meta.get("confidence"),
                entity_names=memory_meta.get("entity_names") or [],
                aliases=memory_meta.get("aliases") or [],
                trigger_terms=memory_meta.get("trigger_terms") or [],
            )
            
            # 사용자 정보 저장
            if user_facts and hasattr(self, 'user_profile') and self.user_profile:
                print(f"[Bridge] 마스터 정보 {len(user_facts)}개 저장")
                for fact in user_facts:
                    self.user_profile.add_fact(
                        content=fact,
                        category="fact",
                        source=f"대화 요약 ({source_timestamp})"
                    )

            if ene_facts and hasattr(self, 'ene_profile') and self.ene_profile:
                print(f"[Bridge] 에네 정보 {len(ene_facts)}개 저장")
                for fact in ene_facts:
                    self.ene_profile.add_fact(
                        content=fact,
                        category="fact",
                        source=f"대화 요약 ({source_timestamp})",
                        origin="auto",
                        auto_update=True,
                    )

            clear_context = getattr(self.llm_client, "clear_context", None)
            if callable(clear_context):
                clear_context()
                print("[Bridge] 대화 요약 후 LLM 세션 컨텍스트 초기화")
            
            # 버퍼 클리어
            self.conversation_buffer = []
            self._ene_thought_context_buffer = []
            self._loaded_topic_memory_context_buffer = []
            
            print(f"[Bridge] 대화 요약 완료: {summary}")
            if user_facts:
                print(f"[Bridge] 마스터 정보 count={len(user_facts)}")
            if ene_facts:
                print(f"[Bridge] 에네 정보 count={len(ene_facts)}")
            
        except Exception as e:
            print(f"[Bridge] 자동 요약 실패: {e}")
            import traceback
            traceback.print_exc()

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
        self._ene_thought_context_buffer = []
        self._loaded_topic_memory_context_buffer = []
        self._last_request_payload = None
        self._last_assistant_response = None
        self._is_rerolling = False
        self._get_attachment_session().clear()
        self._sync_attachment_session_aliases()
        self.away_already_triggered_since_last_user_msg = False
        self.away_trigger_count_since_last_user_msg = 0
        self.last_away_trigger_at = None
        self._cancel_away_pipeline()
        
        # LLM 컨텍스트 초기화
        if self.llm_client:
            self.llm_client.clear_context()
            print("[Bridge] Conversation cleared")
