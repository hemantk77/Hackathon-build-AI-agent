"""Turn reconstructed resource states into the ordered findings/remediation/verification plan."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import OPERATIONS, TREATMENT_OPS
from .linker import CaseContext, Link
from .output import order_steps
from .policy import Policy
from .state import ResourceState, category_of, reconstruct


@dataclass
class CaseResult:
    case_id: str
    status: str
    steps: list
    resources: list = field(default_factory=list)  # diagnostics: (resource, category, treatment, state)
    notes: list = field(default_factory=list)


def _step(phase_op: str, system: str, resource: str, evidence: str) -> dict:
    phase, state = OPERATIONS[phase_op]
    return {"step_no": 0, "phase": phase, "system_id": system, "resource_id": resource,
            "operation": phase_op, "state": state, "evidence_id": evidence}


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
                                case.audit_at, self.file_captured)
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
        resources = [(l.resource_id, l.basis, d.category, d.treatment, s.compliant, s.citation)
                     for l, d, s in states]
        return CaseResult(case.case_id, status, order_steps(steps), resources, notes)

    def _fallback_evidence(self, link: Link, audit_at) -> str:
        """Latest citable (captured <= audit_at) evidence that mentions the record at all."""
        citable = [o for o in self.obs_by_resource.get(link.resource_id, [])
                   if o.obs_time <= audit_at and self.file_captured.get(o.file_id)
                   and self.file_captured[o.file_id] <= audit_at and o.present]
        return citable[-1].file_id if citable else ""
