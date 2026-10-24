"""End-to-end audit pipeline shared by the CLI and the evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .activity import ActivityIndex
from .authorization import classify_request
from .evidence.registry import EvidenceIndex
from .identity import IdentityIndex
from .linker import CaseContext, Linker
from .loaders import Dataset, parse_ts
from .planner import CaseResult, Planner
from .policy import Policy


@dataclass
class RunResult:
    results: list[CaseResult]
    coverage: dict
    linker_diagnostics: list
    auth: dict = field(default_factory=dict)
    llm_usage: list = field(default_factory=list)


def run_pipeline(data_dir: Path, requests_file: str = "deletion_requests.csv", llm=None) -> RunResult:
    ds = Dataset(Path(data_dir), requests_file)
    evidence = EvidenceIndex(ds.data_dir, ds.manifest)
    identity = IdentityIndex(ds.identities, ds.audit_log)
    activity = ActivityIndex(ds.activity)
    policy = Policy(ds.rules)

    predict_ids = {r["case_id"] for r in ds.requests}
    cases: list[CaseContext] = []
    auth = {}
    for row in ds.all_requests():
        decision = classify_request(row["request_text"])
        if llm is not None and row["case_id"] in predict_ids and not decision.confident:
            decision = llm.classify(row["request_text"], decision)
        auth[row["case_id"]] = decision
        cases.append(CaseContext(
            case_id=row["case_id"], request=row, subject=identity.resolve_email(row["email"]),
            requested_at=parse_ts(row["requested_at"]), reported_at=parse_ts(row["reported_at"]),
            audit_at=parse_ts(row["audit_at"]), reported_status=row["reported_status"],
            authorized=decision.authorized, predict=row["case_id"] in predict_ids))

    linker = Linker(cases, evidence, identity, activity)
    links = linker.run()
    planner = Planner(policy, linker.obs_by_resource, evidence.scopes, evidence.captured)
    results = []
    for case in cases:
        if not case.predict:
            continue
        if case.authorized and case.subject is None:
            res = CaseResult(case.case_id, "INCOMPLETE", [], notes=["request email does not resolve to a subject"])
        else:
            res = planner.assess(case, links.get(case.case_id, {}))
        results.append(res)
    return RunResult(results, evidence.coverage_summary(), linker.diagnostics,
                     {k: v.label for k, v in auth.items() if k in predict_ids},
                     llm.usage if llm is not None else [])
