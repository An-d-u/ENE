"""화자와 저장된 대상 연결만 사용하는 보수적인 후속 질문 판정."""

from dataclasses import dataclass
import re

from .profile_review import normalize_subject


@dataclass(frozen=True)
class KnownEntity:
    entity_id: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class FollowupRecall:
    entity_id: str
    entity_name: str
    aliases: tuple[str, ...]
    query: str
    expanded_query: str
    evidence_turn_id: str


def contains_entity(text, name):
    """영문 부분 문자열과 비슷한 이름의 오인 연결을 피한다."""
    normalized = normalize_subject(name)
    if not normalized:
        return False
    suffix = r"(?=$|\W|[은는이가을를의도에과와はがをのにと])"
    return re.search(r"(?<![\w])" + re.escape(normalized) + suffix, normalize_subject(text)) is not None


def collect_known_entities(memories, topics=()):
    names = {}
    for memory in memories or []:
        for name in getattr(memory, "entity_names", []) or []:
            key = normalize_subject(name)
            if key:
                entry = names.setdefault(key, {"name": str(name), "aliases": set()})
                entry["aliases"].update(str(alias) for alias in getattr(memory, "aliases", []) or [])
    for topic in topics or []:
        name = getattr(topic, "keyword", "")
        key = normalize_subject(name)
        if key:
            entry = names.setdefault(key, {"name": str(name), "aliases": set()})
            entry["aliases"].update(str(alias) for alias in getattr(topic, "aliases", []) or [])
    return [KnownEntity(key, value["name"], tuple(sorted(value["aliases"]))) for key, value in names.items()]


def memory_matches_recall(memory, plan):
    names = [*(getattr(memory, "entity_names", []) or []), *(getattr(memory, "aliases", []) or [])]
    return normalize_subject(plan.entity_name) in {normalize_subject(name) for name in names}


_RECALL = (
    re.compile(r"(?:(?:그건|그거|그것은|그때|거기)\s*)?(?:(?:어떤|무슨)\s*(?:색|모양|재료|상태|크기)|(?:몇\s*개)|어디|언제|얼마)(?:이|가|에|였|이었|었|있었|었더라|였더라|이었더라|더라|지|죠|어|야|는|였어|였나|했지|였지|였죠|였을까|던가|였더라|있었지|였더라|이었지|이야|인가|였는지|인지|였더라|\s)*[?.!？]*"),
    re.compile(r"(?:what (?:colou?r|shape|size|material|state) (?:was|is) (?:it|that)|where (?:was|is) (?:it|that)|how many (?:were|was) (?:there|they)|when was (?:it|that))[?.!]*"),
    re.compile(r"(?:それ|あれ)(?:は|の)?(?:何色|どんな形|どこ|いつ|いくつ)(?:だった|でした|です|だ|にあった|の|っけ|か)*[?.!？]*"),
)
_UNSAFE = re.compile(r"['\"“”‘’「」『』]|아니|않|말고|만약|가정|라면|다면|인용|다른 이야기|주제를 바|not\b|if\b|instead\b|someone said|ではない|もし|という")
_TOPIC_SWITCH = re.compile(r"다른\s*(?:이야기|얘기|주제)|주제.{0,5}바|switch\s+topics?|change\s+(?:the\s+)?subject|話[題を].{0,5}変|別の話")


def is_narrow_recall_query(query):
    return any(pattern.fullmatch(normalize_subject(query)) for pattern in _RECALL)


def resolve_followup_recall(query, recent_messages, known_entities):
    normalized = normalize_subject(query)
    if not is_narrow_recall_query(query):
        return None
    aliases = {}
    entities = {entity.entity_id: entity for entity in known_entities}
    for entity in entities.values():
        for name in (entity.name, *entity.aliases):
            aliases.setdefault(normalize_subject(name), set()).add(entity.entity_id)
    if any(contains_entity(query, name) for name in aliases):
        return None
    mentioned = set()
    user_evidence = {}
    for message in recent_messages or []:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "")
        if _TOPIC_SWITCH.search(normalize_subject(text)):
            return None
        matches = {identity for name, identities in aliases.items() if contains_entity(text, name) for identity in identities}
        if matches and _UNSAFE.search(normalize_subject(text)):
            return None
        mentioned.update(matches)
        if message.get("role") == "user" and message.get("turn_id"):
            if not matches and normalize_subject(text) != normalized:
                # 새 사용자 발화에 대상이 없으면 이전 대상의 연속성을 단정하지 않는다.
                user_evidence.clear()
            for identity in matches:
                user_evidence[identity] = str(message["turn_id"])
    if len(mentioned) != 1:
        return None
    identity = next(iter(mentioned))
    if identity not in user_evidence:
        return None
    entity = entities[identity]
    return FollowupRecall(identity, entity.name, entity.aliases, query,
                          f"{entity.name} {query}", user_evidence[identity])
