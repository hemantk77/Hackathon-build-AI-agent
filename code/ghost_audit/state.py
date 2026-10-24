"""Reconstruct each resource's state at a case's audit_at cutoff.

Rules:
* only observations with obs_time <= audit_at are used;
* the latest observation that says something about the required treatment decides;
* a copy in any replica table counts as present (replication drift);
* absence may be inferred from a captured account scope that does not list the record;
* a citation must come from a file whose manifest captured_at <= audit_at.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .evidence.model import Observation, Scope, is_blank

DIRECT_REF_FIELDS = ("customer_reference", "user_id", "subject_selector")


@dataclass
class ResourceState:
    resource_id: str
    system: str
    category: str
    compliant: bool | None  # None = no evidence about the required state
    present: bool | None
    deciding: Observation | Scope | None = None
    citation: str = ""  # file_id usable as evidence (captured <= audit_at)
    history: list = field(default_factory=list)


def category_of(observations: list[Observation], system: str) -> str:
    types = Counter(o.record_type for o in observations if o.record_type)
    if "SUPPORT_ATTACHMENT" in types:
        return "SUPPORT_ATTACHMENT"
    if "SECONDARY_IDENTIFIER" in types:
        return "SECONDARY_IDENTIFIER"
    if types:
        return types.most_common(1)[0][0]
    from .evidence.records import SYSTEM_TYPES

    return SYSTEM_TYPES.get(system, "USER_PROFILE")


def evaluate(obs: Observation, treatment: str) -> bool | None:
    """True = compliant, False = violation, None = observation says nothing about it."""
    status = (obs.status or "").upper()
    f = obs.flags
    if treatment == "DELETE":
        return None if obs.present is None else (not obs.present)
    if treatment in ("REDACT", "ANONYMIZE"):
        if status in ("REDACTED", "ANONYMIZED"):
            return True
        if status == "IDENTIFIABLE":
            return False
        if obs.present is False:
            return True
        if obs.present is None:
            return None
        if obs.has_pii:
            return False
        if treatment == "ANONYMIZE" and any(not is_blank(obs.refs.get(k)) for k in DIRECT_REF_FIELDS):
            return False
        return True
    if treatment == "DISABLE_FLOW":
        if status == "ACTIVE" or f.get("enabled") is True or f.get("scheduler_registered") is True:
            return False
        if status == "DISABLED" or f.get("enabled") is False:
            return True
        return None
    if treatment == "BLOCK_RESTORE":
        if status == "ACTIVE" or f.get("restore_allowed") is True or str(f.get("decision", "")).lower() == "allow":
            return False
        if f.get("eligible") is True and f.get("deletion_block") is not True:
            return False
        if status == "BLOCKED" or f.get("restore_allowed") is False or str(f.get("decision", "")).lower() == "deny" \
                or f.get("deletion_block") is True or f.get("eligible") is False:
            return True
        return None
    if treatment == "RETAIN":
        return None if obs.present is None else bool(obs.present)
    return None


def reconstruct(resource_id: str, system: str, treatment: str, category: str, observations: list[Observation],
                scopes: list[Scope], audit_at: datetime, file_captured: dict) -> ResourceState:
    usable = [o for o in observations if o.obs_time <= audit_at]
    judged = [(o, evaluate(o, treatment)) for o in usable]
    judged = [(o, v) for o, v in judged if v is not None]
    present = None
    for o in reversed(usable):
        if o.present is not None:
            present = o.present
            break
    if judged and treatment == "DELETE" and system == "account_service":
        # The account-store capture taken for this audit (within 30h of the cutoff) is the
        # latest word on whether the profile still exists; it overrides older observations.
        scope = _latest_account_scope(resource_id, system, scopes, audit_at, file_captured)
        if scope is not None and scope.obs_time > judged[-1][0].obs_time and \
                file_captured[scope.file_id] >= audit_at - 30 * _HOUR:
            verdict = resource_id not in scope.listed
            if verdict != judged[-1][1]:  # only a contradiction changes the answer
                return ResourceState(resource_id, system, category, verdict, not verdict, scope,
                                     scope.file_id, [o.file_id for o, _ in judged] + [scope.file_id])
    if judged:
        last_time = judged[-1][0].obs_time
        same_time = [(o, v) for o, v in judged if o.obs_time == last_time]
        # replica drift: at one snapshot instant any surviving copy is a violation
        verdict = all(v for _, v in same_time)
        deciding = next((o for o, v in reversed(same_time) if v == verdict), same_time[-1][0])
        citable = [o for o, v in judged if v == verdict and file_captured.get(o.file_id) and
                   file_captured[o.file_id] <= audit_at]
        citation = citable[-1].file_id if citable else ""
        if not citation and verdict and treatment == "DELETE" and system == "account_service":
            scope = _latest_account_scope(resource_id, system, scopes, audit_at, file_captured)
            if scope is not None and resource_id not in scope.listed and scope.obs_time >= deciding.obs_time - _DAY:
                citation = scope.file_id
        return ResourceState(resource_id, system, category, verdict, present, deciding, citation,
                             [o.file_id for o, _ in judged])
    if treatment == "DELETE" and system == "account_service":
        latest = _latest_account_scope(resource_id, system, scopes, audit_at, file_captured)
        if latest is not None:
            verdict = resource_id not in latest.listed
            return ResourceState(resource_id, system, category, verdict, not verdict, latest,
                                 latest.file_id if verdict else "", [latest.file_id])
    return ResourceState(resource_id, system, category, None, present, None, "", [])


_DAY = timedelta(days=1)
_HOUR = timedelta(hours=1)


def _latest_account_scope(resource_id, system, scopes, audit_at, file_captured):
    """Most recent citable capture of the account store (absence by omission)."""
    captured = [s for s in scopes if s.system == system and s.obs_time <= audit_at and
                file_captured.get(s.file_id) and file_captured[s.file_id] <= audit_at]
    if not captured:
        return None
    return max(captured, key=lambda s: (s.obs_time, file_captured[s.file_id]))
