"""Turn reconstructed resource states into the ordered findings/remediation/verification plan."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import OPERATIONS, TREATMENT_OPS
from .linker import CONFIDENCE_RANK, CaseContext, Link
from .output import order_steps
from .policy import Policy
from .state import ResourceState, category_of, reconstruct


@dataclass
class CaseResult:
    case_id: str
    status: str
    steps: list
    resources: list = field(default_factory=list)  # per-resource diagnostic dicts
    notes: list = field(default_factory=list)
    status_relies_on: str = "direct"  # weakest link confidence the status decision depends on
    step_confidence: list = field(default_factory=list)  # link confidence of each output step


def _step(phase_op: str, system: str, resource: str, evidence: str) -> dict:
    phase, state = OPERATIONS[phase_op]
    return {"step_no": 0, "phase": phase, "system_id": system, "resource_id": resource,
            "operation": phase_op, "state": state, "evidence_id": evidence}


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class Planner:
    def __init__(self, policy: Policy, obs_by_resource: dict, scopes: list, file_captured: dict):
        self.policy = policy
        self.obs_by_resource = obs_by_resource
        self.scopes = scopes
        self.file_captured = file_captured

    def assess(self, case: CaseContext, links: dict[str, Link]) -> CaseResult:
        if not case.authorized:
            return CaseResult(case.case_id, "NOT_APPLICABLE", [], notes=["request does not authorize deletion"])
        states: list[tuple[Link, object, ResourceState]] = []
        for rid, link in sorted(links.items()):
            observations = self.obs_by_resource.get(rid, [])
            category = category_of(observations, link.system)
            latest_flags = {}
            for o in observations:
                if o.obs_time <= case.audit_at:
                    latest_flags.update(o.flags)
            decision = self.policy.decide(category, latest_flags, case.audit_at)
            state = reconstruct(rid, link.system, decision.treatment, category, observations, self.scopes,
                                case.audit_at, self.file_captured, since=case.reported_at)
            states.append((link, decision, state))

        violations = [(l, d, s) for l, d, s in states if s.compliant is False]
        steps = []
        notes = []
        if violations:
            status = "INCOMPLETE"
            for link, decision, state in violations:
                finding, remediation, _ = TREATMENT_OPS[decision.treatment]
                if finding:
                    evidence = state.citation or self._fallback_evidence(link, case.audit_at)
                    if not evidence:
                        notes.append(f"{link.resource_id}: violation seen only in evidence captured after audit_at")
                    steps.append(_step(finding, link.system, link.resource_id, evidence))
                if remediation:
                    steps.append(_step(remediation, link.system, link.resource_id, ""))
            for link, decision, state in states:
                verify = TREATMENT_OPS[decision.treatment][2]
                steps.append(_step(verify, link.system, link.resource_id, ""))
            weakest_needed = max((l.confidence for l, _, _ in violations), key=lambda c: CONFIDENCE_RANK[c])
        else:
            status = "COMPLETE"
            for link, decision, state in states:
                if state.compliant is None or not state.citation:
                    notes.append(f"{link.resource_id}: no citable evidence of final state; omitted from verification")
                    continue
                verify = TREATMENT_OPS[decision.treatment][2]
                if state.present is False and decision.treatment in ("REDACT", "ANONYMIZE"):
                    verify = "VERIFY_RECORD_ABSENT"
                steps.append(_step(verify, link.system, link.resource_id, state.citation))
            weakest_needed = "direct"  # no violation: removing inferred links cannot create one
        ordered = order_steps(steps)
        confidence_of = {l.resource_id: l.confidence for l, _, _ in states}
        resources = [self._describe(l, d, s, case) for l, d, s in states]
        for l, _, _ in states:
            if l.conflicts:
                notes.extend(l.conflicts)
        return CaseResult(case.case_id, status, ordered, resources, notes,
                          status_relies_on=weakest_needed,
                          step_confidence=[confidence_of.get(s["resource_id"], "direct") for s in ordered])

    def _describe(self, link: Link, decision, state: ResourceState, case: CaseContext) -> dict:
        deciding = state.deciding
        return {
            "resource_id": link.resource_id, "system_id": link.system,
            "link": {"confidence": link.confidence, "method": link.method, "basis": link.basis,
                     "evidence_or_activity": link.detail[:6], "candidates": link.candidates,
                     "conflicts": link.conflicts},
            "policy": {"category": decision.category, "rule_id": decision.rule_id, "required_action": decision.action,
                       "treatment": decision.treatment, "condition": decision.note},
            "state_at_audit": {
                "compliant": state.compliant, "present": state.present, "basis": state.basis,
                "deciding_file": getattr(deciding, "file_id", None),
                "deciding_time": _iso(getattr(deciding, "obs_time", None)),
                "citation": state.citation, "rests_only_on_files_captured_after_audit": state.late_only,
                "trail": [{"file_id": f, "captured_at": _iso(c), "observed_at": _iso(t), "kind": k, "compliant": v}
                          for f, c, t, k, v in state.trail[-6:]],
            },
        }

    def _fallback_evidence(self, link: Link, audit_at) -> str:
        """Latest citable (captured <= audit_at) evidence that mentions the record at all."""
        citable = [o for o in self.obs_by_resource.get(link.resource_id, [])
                   if o.obs_time <= audit_at and self.file_captured.get(o.file_id)
                   and self.file_captured[o.file_id] <= audit_at and o.present]
        return citable[-1].file_id if citable else ""
