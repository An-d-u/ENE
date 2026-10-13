"""합성 자료만 사용하는 제품 경로 평가와 실제 요청 예산."""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager, ExitStack, redirect_stdout
from dataclasses import asdict
from hashlib import sha256
import inspect
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock
import time
from types import SimpleNamespace
from unittest.mock import patch


class BudgetExceeded(BaseException):
    """제품의 오류 폴백이 예산 중단을 삼키지 못하게 한다."""


class ApiBudget:
    def __init__(self, limit: int, ledger: Path | None = None):
        if limit < 1:
            raise ValueError("호출 상한은 양수여야 한다")
        self.limit = limit
        self.ledger = ledger
        self.events = json.loads(ledger.read_text(encoding="utf-8"))["events"] if ledger and ledger.exists() else []
        self.stage = "setup"
        self.lock = Lock()

    @property
    def total(self):
        return len(self.events)

    @property
    def by_model(self):
        return dict(Counter(event["model"] for event in self.events))

    def reserve(self, model, stage):
        with self.lock:
            if self.total >= self.limit:
                raise BudgetExceeded("API 호출 상한에 도달했다")
            self.events.append({"model": model, "stage": stage})
            if self.ledger:
                self.ledger.parent.mkdir(parents=True, exist_ok=True)
                self.ledger.write_text(json.dumps({"events": self.events}, ensure_ascii=False, indent=2), encoding="utf-8")


def _request_model(url, body):
    match = re.search(r"/models/([^/:?]+)", str(url))
    if match:
        return match.group(1)
    try:
        return str(json.loads(body or b"{}").get("model") or "unknown")
    except (ValueError, TypeError):
        return "unknown"


@contextmanager
def request_boundary(mode, budget):
    """SDK 내부 재시도도 포함해 HTTP 전송 직전에 집계한다."""
    import httpx
    import requests

    original_sync = httpx.Client._send_single_request
    original_async = httpx.AsyncClient._send_single_request
    original_requests = requests.adapters.HTTPAdapter.send

    def reserve(url, body):
        if mode == "mock":
            raise AssertionError("mock 평가에서 외부 요청이 발생했다")
        budget.reserve(_request_model(url, body), budget.stage)

    def sync_send(client, request):
        reserve(request.url, request.content)
        return original_sync(client, request)

    async def async_send(client, request):
        reserve(request.url, request.content)
        return await original_async(client, request)

    def requests_send(adapter, request, **kwargs):
        if adapter.max_retries.total:
            raise ValueError("집계되지 않는 전송 계층 재시도는 허용하지 않는다")
        reserve(request.url, request.body)
        return original_requests(adapter, request, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(httpx.Client, "_send_single_request", sync_send))
        stack.enter_context(patch.object(httpx.AsyncClient, "_send_single_request", async_send))
        stack.enter_context(patch.object(requests.adapters.HTTPAdapter, "send", requests_send))
        if mode == "mock":
            stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("외부 연결 금지")))
        yield


@contextmanager
def isolated_storage():
    """앱을 불러오기 전에 저장 루트와 기본 프롬프트를 격리한다."""
    previous = os.environ.get("ENE_USER_DATA_DIR")
    with TemporaryDirectory(prefix="ene-memory-eval-") as directory:
        root = Path(directory)
        os.environ["ENE_USER_DATA_DIR"] = str(root)
        defaults = Path(__file__).resolve().parents[1] / "prompts" / "defaults"
        if defaults.exists():
            shutil.copytree(defaults, root / "prompts")
        try:
            from src.ai import prompt_config
            with ExitStack() as stack:
                stack.enter_context(patch.object(prompt_config, "PROMPT_CONFIG_DIR", root / "prompts"))
                for name, filename in (
                    ("BASE_SYSTEM_PROMPT_PATH", "base_system_prompt.md"),
                    ("SUB_PROMPT_BODY_PATH", "sub_prompt_body.md"),
                    ("EMOTION_GUIDES_PATH", "emotion_guides.md"),
                    ("LIFE_WORLD_PROMPT_PATH", "life_world.md"),
                ):
                    stack.enter_context(patch.object(prompt_config, name, root / "prompts" / filename))
                stack.enter_context(patch.object(prompt_config, "_should_sync_store_python_prompt_dirs", return_value=False))
                yield root
        finally:
            if previous is None:
                os.environ.pop("ENE_USER_DATA_DIR", None)
            else:
                os.environ["ENE_USER_DATA_DIR"] = previous


class SyntheticEmbedding:
    """정답을 참조하지 않는 어휘 해시 대역. 의미 품질 점수가 아니다."""

    provider = "mock"
    model = "lexical-hash"

    async def embed(self, text):
        vector = [0.0] * 256
        for token in re.findall(r"\w+", text.casefold()):
            index = int.from_bytes(sha256(token.encode()).digest()[:2], "big") % len(vector)
            vector[index] += 1
        return vector

    async def embed_batch(self, texts):
        return [await self.embed(text) for text in texts]

    @staticmethod
    def cosine_similarity(left, right):
        from src.ai.embedding import EmbeddingGenerator
        return EmbeddingGenerator.cosine_similarity(left, right)


def _evaluation_settings():
    # 실제 설정의 대화·프로필·이름·도구 경로를 복사하지 않는다.
    config = {
        "prompt_language": "ko", "enable_mood_system": False,
        "enable_proactive_conversation": False, "enable_ene_goals": False,
        "web_search_enabled": False, "web_search_auto_enabled": False,
        "enable_schedule_recognition": False, "enable_conversation_promises": False,
        "enable_ene_thoughts": False, "enable_response_analysis": False,
        "max_recent_memories": 0, "max_important_memories": 0,
        "max_profile_facts_in_context": 10,
    }
    return SimpleNamespace(config=config, get=lambda key, default=None: config.get(key, default))


async def _run_case(case, root, mode, config, budget):
    from src.ai.embedding import create_embedding_generator
    from src.ai.ene_profile import EneProfile
    from src.ai.knowledge_map import KnowledgeMapManager
    from src.ai.llm_provider import create_llm_client, LLMProviderConfig
    from src.ai.memory import MemoryManager
    from src.ai.memory_context_builder import build_memory_context
    from src.ai.tool_calling import compose_contextual_message
    from src.ai.memory_types import MemoryContextTrace, MemoryEntry
    from src.ai.user_profile import UserProfile, ProfileFact
    from src.core.bridge_mixins.memory_summary import MemorySummaryBridgeMixin

    root.mkdir()
    settings = _evaluation_settings()
    embedding = SyntheticEmbedding() if mode == "mock" else create_embedding_generator(
        provider=config["embedding_provider"], model=config["embedding_model"],
        api_key=os.environ["ENE_EVAL_EMBEDDING_KEY"], api_url=config.get("embedding_api_url", ""),
    )
    manager = MemoryManager(root / "memory.json", embedding_generator=embedding)
    profile = UserProfile(root / "user_profile.json")
    profile.facts = [ProfileFact.from_dict(fact) for fact in case["seed_state"]["facts"]]
    ene = EneProfile(root / "ene_profile.json", user_profile=profile)
    knowledge = KnowledgeMapManager(root / "knowledge_map.json", embedding_generator=embedding)
    budget.stage = "seed_embedding"
    seeds = case["seed_state"]["memories"]
    vectors = await embedding.embed_batch([memory["summary"] for memory in seeds])
    for memory, vector in zip(seeds, vectors):
        manager.memories.append(MemoryEntry(
            id=memory["id"], summary=memory["summary"], timestamp=memory["timestamp"],
            original_messages=[dict(message, turn_index=i, conversation_id=memory["id"]) for i, message in enumerate(memory["messages"])],
            entity_names=memory["entity_names"], aliases=memory.get("aliases", []),
            embedding=vector, embedding_provider=embedding.provider, embedding_model=embedding.model,
        ))
    client = create_llm_client(
        LLMProviderConfig(provider=config.get("provider", "gemini"),
                          api_key=os.environ.get("ENE_EVAL_LLM_KEY", "synthetic-test-key"),
                          model_name=config.get("model", "synthetic-model"),
                          generation_params={"max_tokens": config.get("response_tokens", 1024)}),
        settings=settings, memory_manager=manager, user_profile=profile, ene_profile=ene,
        knowledge_map_manager=knowledge,
    )
    if hasattr(client, "_summary_output_token_budget"):
        client._summary_output_token_budget = lambda: config.get("summary_tokens", 2048)
    bridge = MemorySummaryBridgeMixin()
    bridge.llm_client, bridge.memory_manager = client, manager
    bridge.user_profile, bridge.ene_profile, bridge.knowledge_map_manager = profile, ene, knowledge
    storage = []
    raw_summaries = []
    for session in case["sessions"]:
        if not session.get("summarize"):
            continue
        messages = [(message["role"], message["text"], message["timestamp"]) for message in session["messages"]]
        bridge.conversation_buffer = messages
        budget.stage = "summary"
        if mode == "mock":
            # 수동 고정 대역은 원문 보존만 시험하며 의미 추출을 흉내 내지 않는다.
            response = "[SUMMARY]\n" + "\n".join(message[1] for message in messages) + "\n[MASTER_INFO]\n없음\n[ENE_INFO]\n없음\n[MEMORY_META]\nmemory_type: general\n[PROFILE_UPDATES]\n[]"
            client._request_summary_text = lambda _prompt, value=response: value
        request_summary = getattr(client, "_request_summary_text", None)
        if request_summary:
            def capture(prompt, original=request_summary):
                value = original(prompt)
                raw_summaries.append(value)
                return value
            client._request_summary_text = capture
        pending = await bridge._build_summary_review_state(messages)
        bridge._pending_summary_review = pending
        facts = list(pending["user_facts"])
        actions = case["review_actions"]
        for action in actions:
            if action["action"] == "reject":
                updates = pending["memory_meta"].get("profile_updates", [])
                rejected = {f"[{item.get('category')}] {item.get('content')}" for item in updates if item.get("evidence") == action.get("evidence")}
                facts = [fact for fact in facts if fact not in rejected]
            elif action["action"] == "delete_target":
                profile.facts = [fact for fact in profile.facts if fact.id != action["target_id"]]
            elif action["action"] == "edit_target":
                target = next(fact for fact in profile.facts if fact.id == action["target_id"])
                target.content = "별도의 합성 절차로 변경된 상태다."
        budget.stage = "review_storage"
        try:
            saved = await bridge._persist_reviewed_summary(pending["summary"], facts, pending["ene_facts"], pending["memory_meta"], pending["topic_hints"])
            storage.append({"memory_id": saved.id, "status": "persisted", "selected_facts": facts})
        except Exception as error:
            storage.append({"status": "failed", "error": type(error).__name__})
    trace = MemoryContextTrace()
    recent_messages = [dict(message, turn_id=message["id"]) for session in case["sessions"] for message in session["messages"]]
    recent = "\n".join(f"{message['role']}: {message['text']}" for message in recent_messages)
    budget.stage = "retrieval"
    kwargs = {"recent_context": recent, "trace": trace}
    if "recent_memory_messages" in inspect.signature(build_memory_context).parameters:
        kwargs["recent_memory_messages"] = recent_messages
    context = await build_memory_context(client, case["query"], **kwargs)
    composed = compose_contextual_message(case["query"], memory_context=context)
    budget.stage = "response"
    answer = "" if mode == "mock" else client.send_message(composed, history_user_content=case["query"])
    if inspect.isawaitable(answer):
        answer = await answer
    selected_turns = []
    for mid, start, end in trace.raw_chunks:
        seed = next((item for item in seeds if item["id"] == mid), None)
        if seed:
            selected_turns.extend(message["id"] for message in seed["messages"][start:end + 1])
    selected = {"memory_ids": trace.summary_ids, "fact_ids": trace.fact_ids, "turn_ids": selected_turns}
    missing = {key: sorted(set(case["expected"][key]) - set(values)) for key, values in selected.items()}
    return {
        "id": case["id"], "gate": case["gate"], "group": case["group"],
        "trace": trace.to_dict(), "missing_evidence": missing,
        "storage": storage, "raw_summary_outputs": raw_summaries,
        "final_facts": [asdict(fact) for fact in profile.facts],
        "answer": answer, "answer_grade": "ungraded",
        "input_chars": len(composed), "token_usage": getattr(client, "_last_token_usage", None) or "unknown",
    }


async def evaluate(cases, *, mode, config=None, budget=None):
    config = dict(config or {})
    budget = budget or ApiBudget(config.get("max_api_requests", 1))
    start = time.monotonic()
    results = []
    status = "complete"
    with isolated_storage() as root, request_boundary(mode, budget):
        for index, case in enumerate(cases):
            try:
                # 제품의 진단 출력에 합성 원문이 있어도 평가 보고서로만 전달한다.
                with redirect_stdout(io.StringIO()):
                    result = await _run_case(case, root / str(index), mode, config, budget)
                results.append(result)
            except BudgetExceeded:
                status = "budget_exhausted"
                break
    repository = Path(__file__).resolve().parents[1]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=True).stdout.strip()
    return {
        "mode": mode, "status": status, "answer_grade": "ungraded", "code_commit": revision,
        "fixture_hash": sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "prompt_hash": sha256((repository / "src/ai/summary_prompt.py").read_bytes()).hexdigest(),
        "config": config, "api_requests": budget.total, "calls_by_model": budget.by_model,
        "cases": results, "elapsed_seconds": round(time.monotonic() - start, 3),
    }
