"""서버가 소유하는 프로필 교체 검토와 순수 판정 규칙."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import unicodedata
from uuid import uuid4


def normalize_subject(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def fact_fingerprint(fact):
    data = fact.to_dict() if hasattr(fact, "to_dict") else fact
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProfileProposal:
    proposal_id: str
    update: dict
    target_id: str
    snapshot: dict | None
    fingerprint: str
    conflicting: bool = False

    @property
    def subject_conflict(self):
        return bool(self.snapshot is not None and (
            not normalize_subject(self.snapshot.get("subject"))
            or normalize_subject(self.snapshot.get("subject")) != normalize_subject(self.update.get("subject"))
        ))


@dataclass(frozen=True)
class ReviewedUpdate:
    proposal: ProfileProposal
    update: dict
    manual_edit: bool = False
    subject_confirmed: bool = False

    def decision(self, facts):
        proposal = self.proposal
        if proposal.conflicting:
            return "skip"
        target = next((fact for fact in facts if fact.id == proposal.target_id), None)
        if proposal.target_id:
            if target is None or fact_fingerprint(target) != proposal.fingerprint:
                return "refresh"
            changed_subject = (
                not normalize_subject(target.subject)
                or normalize_subject(target.subject) != normalize_subject(self.update.get("subject"))
            )
            if changed_subject and not self.subject_confirmed:
                return "skip"
        elif any(fact.category == self.update.get("category") and normalize_subject(fact.subject) == normalize_subject(self.update.get("subject")) for fact in facts):
            return "refresh"
        return "apply"


def make_proposals(facts, updates):
    proposals = []
    allowed = {"category", "content", "subject", "state", "assertion", "evidence", "replaces", "effective_at"}
    for raw in updates if isinstance(updates, list) else []:
        if not isinstance(raw, dict):
            continue
        update = {key: deepcopy(value) for key, value in raw.items() if key in allowed}
        target_id = str(update.get("replaces") or "")
        target = next((fact for fact in facts if fact.id == target_id), None)
        if not target_id:
            matches = [fact for fact in facts if fact.category == update.get("category") and normalize_subject(fact.subject) and normalize_subject(fact.subject) == normalize_subject(update.get("subject"))]
            if len(matches) == 1:
                target = matches[0]
                target_id = target.id
            elif len(matches) > 1:
                proposals.append(ProfileProposal(uuid4().hex, update, "", None, "", True))
                continue
        update["replaces"] = target_id
        proposals.append(ProfileProposal(uuid4().hex, update, target_id, deepcopy(target.to_dict()) if target else None, fact_fingerprint(target) if target else ""))
    targets = {}
    for proposal in proposals:
        if proposal.target_id:
            targets.setdefault(proposal.target_id, []).append(proposal)
    conflicting_ids = {target for target, entries in targets.items() if len({fact_fingerprint(item.update) for item in entries}) > 1}
    return [ProfileProposal(item.proposal_id, item.update, item.target_id, item.snapshot, item.fingerprint, item.conflicting or item.target_id in conflicting_ids) for item in proposals]


def review_proposal(proposal, *, edits=None, confirm_subject=False):
    update = deepcopy(proposal.update)
    editable = {"category", "content", "state", "subject"}
    for key, value in (edits or {}).items():
        if key in editable and isinstance(value, str):
            update[key] = value.strip()
    manual = any(update.get(key) != proposal.update.get(key) for key in editable)
    return ReviewedUpdate(proposal, update, manual, confirm_subject is True)
