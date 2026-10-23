"""합성 자료만 사용하는 제품 경로 평가와 실제 요청 예산."""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager, ExitStack, redirect_stdout
from dataclasses import asdict
from datetime import datetime
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


class EvaluationEmbeddingCache:
    """같은 평가 실행 안에서 동일 모델·문자열의 실제 임베딩만 재사용한다."""

    def __init__(self, generator, cache):
        self.generator = generator
        self.cache = cache
        self.hits = 0

    def __getattr__(self, name):
        return getattr(self.generator, name)

    async def embed(self, text):
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts):
        keys = [(self.provider, self.model, text) for text in texts]
        missing = list(dict.fromkeys(key for key in keys if key not in self.cache))
        self.hits += len(keys) - len(missing)
        if missing:
            vectors = await self.generator.embed_batch([key[2] for key in missing])
            if len(vectors) != len(missing) or any(not vector for vector in vectors):
                raise RuntimeError("임베딩 캐시에 불완전한 배치를 저장할 수 없습니다")
            self.cache.update((key, list(vector)) for key, vector in zip(missing, vectors))
        return [list(self.cache[key]) for key in keys]


class MeasuredEmbedding:
    """캐시 뒤 실제 생성기에 전달한 논리 호출과 입력 수를 구분한다."""

    def __init__(self, generator, budget):
        self.generator, self.budget = generator, budget
        self.embedding_usage = {"logical_calls": 0, "inputs": 0, "by_stage": {}}

    def __getattr__(self, name):
        return getattr(self.generator, name)

    async def embed(self, text):
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts):
        if not texts:
            return []
        self.embedding_usage["logical_calls"] += 1
        self.embedding_usage["inputs"] += len(texts)
        stage = self.embedding_usage["by_stage"].setdefault(self.budget.stage, {"calls": 0, "inputs": 0})
        stage["calls"] += 1
        stage["inputs"] += len(texts)
        return await self.generator.embed_batch(texts)


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


def _evaluation_settings(options=None):
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
    if options and "experience_mode" in options:
        config["experience_memory_enabled"] = options["experience_mode"] == "enabled"
    return SimpleNamespace(config=config, get=lambda key, default=None: config.get(key, default))


def prepare_review_actions(pending, profile, actions):
    """사전 검토 동작을 출력 순서가 아닌 서버 대상과 사용자 근거에 연결한다."""
    from src.ai.profile_review import normalize_subject
    proposals = pending.get("profile_proposals", [])
    rows = {proposal.proposal_id: {"proposal_id": proposal.proposal_id, "selected": True}
            for proposal in proposals}
    outcomes = []
    for action in actions:
        kind = action["action"]
        if kind in {"edit_target", "delete_target"}:
            target = next((fact for fact in profile.facts if fact.id == action["target_id"]), None)
            if target:
                if kind == "delete_target":
                    profile.facts.remove(target)
                else:
                    target.content = "별도의 합성 절차로 변경된 상태다."
            outcomes.append({"action": kind, "status": "applied" if target else "missing_target"})
        if not action.get("evidence"):
            if kind == "approve":
                outcomes.append({"action": kind, "status": "applied"})
            continue
        evidence = normalize_subject(action["evidence"])
        matches = []
        for proposal in proposals:
            proposed_evidence = normalize_subject(proposal.update.get("evidence"))
            same_target = (proposal.target_id == action.get("target_id") or
                           normalize_subject(proposal.update.get("subject")) == normalize_subject(action.get("subject")))
            if same_target and proposed_evidence and (proposed_evidence in evidence or evidence in proposed_evidence):
                matches.append(proposal)
        if len(matches) != 1:
            outcomes.append({"action": kind, "status": "missing_proposal" if not matches else "ambiguous_proposal"})
            continue
        if kind == "correct_subject" and matches[0].target_id != action.get("target_id"):
            outcomes.append({"action": kind, "status": "missing_target_binding"})
            continue
        row = rows[matches[0].proposal_id]
        if kind == "reject":
            row["selected"] = False
        elif kind == "correct_subject":
            row.update(edits={"subject": action["corrected_subject"]}, confirm_subject=True)
        outcomes.append({"action": kind, "status": "applied", "proposal_id": matches[0].proposal_id})
    payload = {key: pending.get(key) for key in ("review_id", "summary", "user_facts", "ene_facts", "memory_meta", "topic_hints")}
    payload["profile_selections"] = list(rows.values())
    return payload, outcomes


def grade_state(expected, before_storage, final_facts):
    """금지 덮어쓰기는 정확히 검사하고 자연어 정정은 별도 검토 대상으로 남긴다."""
    before = {fact["id"]: fact for fact in before_storage}
    final = {fact["id"]: fact for fact in final_facts}
    forbidden = [item["fact_id"] for item in expected["forbidden_changes"]
                 if before.get(item["fact_id"]) != final.get(item["fact_id"])]
    corrections = []
    for expected_fact in expected["corrections"]:
        actual = final.get(expected_fact["fact_id"])
        status = "exact_match"
        if actual is None:
            status = "missing_target"
        elif any(actual.get(key) != value for key, value in expected_fact.items() if key not in {"fact_id", "content"}):
            status = "incorrect_state"
        elif "content" in expected_fact and actual.get("content") != expected_fact["content"] and actual.get("content") == before.get(expected_fact["fact_id"], {}).get("content"):
            status = "not_applied"
        elif any(actual.get(key) != value for key, value in expected_fact.items() if key != "fact_id"):
            status = "review_required"
        corrections.append({"fact_id": expected_fact["fact_id"], "status": status})
    return {"forbidden_changes": forbidden, "corrections": corrections}


def compose_evaluation_message(query, context, settings, recent=""):
    """제품과 동일하게 비활성 웹 검색의 상태 문구까지 포함한다."""
    from src.ai.tool_calling import build_web_search_context_from_settings, compose_contextual_message
    web_context = build_web_search_context_from_settings(settings, message=query, recent_context=recent)
    return compose_contextual_message(query, memory_context=context, web_search_context=web_context)


def restore_recent_conversation(client, sessions):
    """끝난 요약 세션은 기억으로, 진행 중 발화는 제품의 대화 이력으로 전달한다."""
    messages = [(message["role"], message["text"], message["timestamp"])
                for session in sessions if not session.get("summarize")
                for message in session["messages"]]
    if messages and not client.rebuild_context_from_conversation(messages):
        raise RuntimeError("평가의 최근 대화 이력을 구성하지 못했습니다")


async def _run_case(case, root, mode, config, budget, embedding_cache=None):
    from src.ai.embedding import create_embedding_generator
    from src.ai.ene_profile import EneProfile
    from src.ai.knowledge_map import KnowledgeMapManager
    from src.ai.llm_provider import create_llm_client, LLMProviderConfig
    from src.ai.memory import MemoryManager
    from src.ai.memory_context_builder import build_memory_context
    from src.ai.memory_types import MemoryContextTrace, MemoryEntry
    from src.ai.user_profile import UserProfile, ProfileFact
    from src.core.bridge_mixins.memory_summary import MemorySummaryBridgeMixin

    root.mkdir()
    settings = _evaluation_settings(config)
    embedding = SyntheticEmbedding() if mode == "mock" else create_embedding_generator(
        provider=config["embedding_provider"], model=config["embedding_model"],
        api_key=os.environ["ENE_EVAL_EMBEDDING_KEY"], api_url=config.get("embedding_api_url", ""),
    )
    embedding = MeasuredEmbedding(embedding, budget)
    if embedding_cache is not None:
        embedding = EvaluationEmbeddingCache(embedding, embedding_cache)
    manager = MemoryManager(root / "memory.json", embedding_generator=embedding)
    profile = UserProfile(root / "user_profile.json")
    profile.facts = [ProfileFact.from_dict(fact) for fact in case["seed_state"]["facts"]]
    ene = EneProfile(root / "ene_profile.json", user_profile=profile)
    knowledge = KnowledgeMapManager(root / "knowledge_map.json", embedding_generator=embedding)
    budget.stage = "seed_embedding"
    seeds = case["seed_state"]["memories"]
    vectors = await embedding.embed_batch([memory["summary"] for memory in seeds])
    if len(vectors) != len(seeds):
        raise RuntimeError("평가 준비 중 임베딩 개수가 달라 기억을 구성할 수 없습니다")
    for memory, vector in zip(seeds, vectors):
        manager.memories.append(MemoryEntry(
            id=memory["id"], summary=memory["summary"], timestamp=memory["timestamp"],
            original_messages=[dict(message, turn_index=i, conversation_id=memory["id"]) for i, message in enumerate(memory["messages"])],
            entity_names=memory["entity_names"], aliases=memory.get("aliases", []),
            embedding=vector, embedding_provider=embedding.provider, embedding_model=embedding.model,
        ))
    from src.ai.knowledge_map_types import TopicMemoryTopic
    knowledge.topics = [TopicMemoryTopic.from_dict(topic) for topic in case["seed_state"].get("topics", [])]
    knowledge.last_updated = case.get("now")
    if knowledge.topics:
        await knowledge.regenerate_embeddings()
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
    review_outcomes = []
    before_storage = [asdict(fact) for fact in profile.facts]
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
        payload, outcomes = prepare_review_actions(pending, profile, case["review_actions"])
        review_outcomes.extend(outcomes)
        before_storage = [asdict(fact) for fact in profile.facts]
        budget.stage = "review_storage"
        try:
            resolved = bridge._resolve_profile_review_payload(payload)
            saved = await bridge._persist_reviewed_summary(resolved["summary"], resolved["user_facts"], resolved["ene_facts"], resolved["memory_meta"], resolved["topic_hints"])
            storage.append({"memory_id": saved.id, "status": "persisted", "selected_facts": resolved["user_facts"],
                            "checkpoints": pending.get("checkpoints", {})})
        except Exception as error:
            storage.append({"status": "failed", "error": type(error).__name__})
    if case["group"] == "experience":
        return await _run_experience_dialogue(case, client, manager, profile, settings, mode, budget, embedding,
                                              storage, raw_summaries, review_outcomes, before_storage)
    trace = MemoryContextTrace()
    recent_messages = [dict(message, turn_id=message["id"]) for session in case["sessions"] for message in session["messages"]]
    recent = "\n".join(f"{message['role']}: {message['text']}" for message in recent_messages)
    budget.stage = "retrieval"
    kwargs = {"recent_context": recent, "trace": trace}
    if "recent_memory_messages" in inspect.signature(build_memory_context).parameters:
        kwargs["recent_memory_messages"] = recent_messages
    context = await build_memory_context(client, case["query"], **kwargs)
    composed = compose_evaluation_message(case["query"], context, settings, recent)
    restore_recent_conversation(client, case["sessions"])
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
        "review_actions": review_outcomes,
        "state_grade": grade_state(case["expected"], before_storage, [asdict(fact) for fact in profile.facts]),
        "final_facts": [asdict(fact) for fact in profile.facts],
        "before_storage": before_storage,
        "embedding_cache_hits": getattr(embedding, "hits", 0),
        "embedding_usage": embedding.embedding_usage,
        "response_history": "unsummarized_sessions",
        "answer": answer, "answer_grade": "ungraded",
        "input_chars": len(composed), "token_usage": getattr(client, "_last_token_usage", None) or "unknown",
    }


@contextmanager
def evaluation_clock(iso_time):
    """사건 시간과 가중치의 기준 시각을 합성 사례에 고정한다."""
    fixed = datetime.fromisoformat(iso_time)
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    with ExitStack() as stack:
        for module in ("src.ai.memory", "src.ai.knowledge_map", "src.ai.memory_context_builder", "src.ai.date_query_parser"):
            stack.enter_context(patch(module + ".datetime", FrozenDatetime))
        yield


async def _run_experience_dialogue(case, client, manager, profile, settings, mode, budget, embedding,
                                   storage, raw_summaries, review_outcomes, before_storage):
    from src.ai.memory_context_builder import build_memory_context
    from src.ai.memory_types import MemoryContextTrace
    recent_messages = [dict(message, turn_id=message["id"]) for session in case["sessions"]
                       if not session.get("summarize") for message in session["messages"]]
    restore_recent_conversation(client, case["sessions"])
    turns = []
    selected_refs = set()
    for index, turn in enumerate([{"query": case["query"]}, *case.get("followups", [])]):
        trace = MemoryContextTrace()
        recent = "\n".join(f"{message['role']}: {message['text']}" for message in recent_messages)
        budget.stage = "retrieval"
        started = time.perf_counter()
        context = await build_memory_context(client, turn["query"], recent_context=recent, trace=trace,
                                             recent_memory_messages=recent_messages,
                                             memory_request_id=f"{case['id']}:{index}")
        retrieval_ms = (time.perf_counter() - started) * 1000
        composed = compose_evaluation_message(turn["query"], context, settings, recent)
        budget.stage = "response"
        answer = "" if mode == "mock" else client.send_message(composed, history_user_content=turn["query"])
        if inspect.isawaitable(answer):
            answer = await answer
        answer_text = str(answer[0]) if isinstance(answer, (tuple, list)) and answer else str(answer)
        if index == 0:
            selected_refs = {f"{mid}:{i}" for mid, start, end in trace.raw_chunks for i in range(start, end + 1)}
            for ref in trace.experience_refs:
                selected_refs.update(f"{ref['memory_id']}:{i}" for i in ref["turn_indexes"])
                if ref.get("history_revision"):
                    selected_refs.add(f"history:{ref['memory_id']}:{ref['history_revision']}")
        turns.append({"query": turn["query"], "answer": answer, "trace": trace.to_dict(),
                      "context": context, "input_chars": len(composed), "retrieval_ms": round(retrieval_ms, 3),
                      "token_usage": getattr(client, "_last_token_usage", None) or "unknown",
                      "previous_response_source": ("generated" if mode == "live" else "mock") if index else None})
        recent_messages.extend([
            {"role": "user", "text": turn["query"], "turn_id": f"current-{index}-u", "timestamp": case["now"]},
            {"role": "assistant", "text": answer_text, "turn_id": f"current-{index}-a", "timestamp": case["now"]},
        ])
    missing = sorted(set(case["expected"]["required_evidence_refs"]) - selected_refs)
    return {"id": case["id"], "group": case["group"], "gate": case["gate"], "evaluation_now": case["now"],
            "fixture_case_hash": sha256(json.dumps(case, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "experience": {"policy": case["expected"]["connection_policy"], "family": case["family"]},
            "trace": turns[0]["trace"], "answer": turns[0]["answer"], "answer_grade": "ungraded", "turns": turns,
            "missing_evidence": {"experience_refs": missing}, "storage": storage, "raw_summary_outputs": raw_summaries,
            "review_actions": review_outcomes, "state_grade": grade_state(case["expected"], before_storage, [asdict(f) for f in profile.facts]),
            "before_storage": before_storage, "final_facts": [asdict(f) for f in profile.facts],
            "embedding_cache_hits": getattr(embedding, "hits", 0), "response_history": "generated_unsummarized_turns",
            "embedding_usage": embedding.embedding_usage,
            "input_chars": sum(turn["input_chars"] for turn in turns)}


async def evaluate(cases, *, mode, config=None, budget=None, embedding_cache=None):
    config = dict(config or {})
    budget = budget or ApiBudget(config.get("max_api_requests", 1))
    start = time.monotonic()
    requests_before = budget.total
    results = []
    status = "complete"
    if embedding_cache is None and config.get("cache_embeddings"):
        embedding_cache = {}
    with isolated_storage() as root, request_boundary(mode, budget):
        for index, case in enumerate(cases):
            try:
                # 제품의 진단 출력에 합성 원문이 있어도 평가 보고서로만 전달한다.
                with redirect_stdout(io.StringIO()), evaluation_clock(case["now"]):
                    result = await _run_case(case, root / str(index), mode, config, budget, embedding_cache)
                result["run_index"] = index
                results.append(result)
            except BudgetExceeded:
                status = "budget_exhausted"
                break
    repository = Path(__file__).resolve().parents[1]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=True).stdout.strip()
    prompt_paths = [repository / "src/ai/summary_prompt.py", repository / "src/ai/experience_memory.py",
                    repository / "src/ai/memory_context_builder.py", *sorted((repository / "prompts/defaults").glob("*"))]
    prompt_hashes = {str(path.relative_to(repository)): sha256(path.read_bytes()).hexdigest()
                     for path in prompt_paths if path.is_file()}
    effective_settings = _evaluation_settings(config).config
    return {
        "mode": mode, "status": status, "answer_grade": "ungraded", "code_commit": revision,
        "fixture_hash": sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "prompt_hash": sha256((repository / "src/ai/summary_prompt.py").read_bytes()).hexdigest(),
        "prompt_hashes": prompt_hashes,
        "settings": effective_settings,
        "settings_hash": sha256(json.dumps(effective_settings, sort_keys=True).encode()).hexdigest(),
        "run_api_requests": budget.total - requests_before,
        "config": config, "api_requests": budget.total, "calls_by_model": budget.by_model,
        "cases": results, "elapsed_seconds": round(time.monotonic() - start, 3),
    }
