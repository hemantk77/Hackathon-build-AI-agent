"""Resource discovery: which records belong to each case's subject.

Link bases, strongest first:
  evidence   - an observation carrying one of the subject's identifiers (current or historical
               email, email hash, phone, stable user_id), observed within [requested_at, audit_at]
  catalog    - a LINK_RESOURCE_IDENTITY activity row naming the subject, within the same window
  document   - a PDF/screenshot whose text ties the resource to the subject
  workflow   - a deletion-worker event emitted in this request's reporting slot, resolved by
               constraint elimination across all requests (see assign_workflow)
  alignment  - workflow tie resolved by record order inside a snapshot bundle
  tie_guess  - remaining workflow tie, resolved deterministically (low confidence)
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .activity import ActivityIndex
from .evidence.model import EMAIL_RE, Observation, keys_from_value, system_for_resource
from .evidence.registry import EvidenceIndex
from .identity import IdentityIndex, Subject

HOUR = timedelta(hours=1)
STATUS_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}
OCR_RESOURCE_RE = re.compile(
    r"(?<![A-Za-z_])(account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|cache|"
    r"email_delivery|marketing|legal_hold|object)_([0-9oO]{1,6})(?![0-9])"
)


@dataclass
class CaseContext:
    case_id: str
    request: dict
    subject: Subject | None
    requested_at: datetime
    reported_at: datetime
    audit_at: datetime
    reported_status: str
    authorized: bool
    predict: bool = True  # False for context-only requests (other request files)

    @property
    def keys(self) -> set:
        return self.subject.keys if self.subject else set()


@dataclass
class Link:
    resource_id: str
    system: str
    basis: str
    detail: list = field(default_factory=list)


def _norm_ocr(text: str) -> str:
    return text.replace("·", " ").replace("·", " ")


def wf_kind(a) -> str:
    d = a.details
    if a.event_type == "DELETE_RECORD" and a.target == "account_service" and "primary profile" in d:
        return "account"
    if "requested operation" in d or "stopped after" in d or "internal work" in d:
        return "direct"
    if "Policy action completed" in d:
        return "success"
    return "followup"


WINDOWS = {  # hours relative to reported_at
    "account": (-1.6, -0.4),
    "success": (-0.75, 0.05),
    "followup": (0.25, 2.3),
    "direct": (-0.35, 0.35),
}


class Linker:
    def __init__(self, cases: list[CaseContext], evidence: EvidenceIndex, identity: IdentityIndex,
                 activity: ActivityIndex):
        self.cases = cases
        self.by_case = {c.case_id: c for c in cases}
        self.evidence = evidence
        self.identity = identity
        self.activity = activity
        self.ambiguous_keys = {k for k, owners in identity.key_owner.items() if len(owners) > 1}
        self.doc_observations: list[Observation] = self._document_observations()
        self.all_observations = evidence.observations + self.doc_observations
        self.obs_by_resource = defaultdict(list)
        for o in self.all_observations:
            self.obs_by_resource[o.resource_id].append(o)
        for lst in self.obs_by_resource.values():
            lst.sort(key=lambda o: (o.obs_time, o.captured_at, o.file_id, o.position))
        self.owners = self._all_time_owners()
        self.links: dict[str, dict[str, Link]] = {c.case_id: {} for c in cases}
        self.diagnostics: list[dict] = []

    # ------------------------------------------------------------------ documents
    def _document_observations(self) -> list[Observation]:
        out = []
        for doc in self.evidence.docs:
            text = _norm_ocr(doc.text)
            lines = text.splitlines()
            doc_keys = set()
            for line in lines:
                doc_keys |= keys_from_value(line)
            owners = self.identity.owners_of(doc_keys - self.ambiguous_keys)
            single_subject_keys = doc_keys if len(owners) == 1 else set()
            found: dict[str, set] = {}

            def row_keys(line: str) -> set:
                # A row ties a record to a subject only through a direct identifier on that row
                # (email / phone / email hash); a bare user reference is accepted alongside one.
                keys = keys_from_value(line)
                return keys if any(k.split(":")[0] in ("email", "phone", "hash") for k in keys) else set()

            for line in lines:
                for m in OCR_RESOURCE_RE.finditer(line):
                    rid = f"{m.group(1)}_{m.group(2).replace('o', '0').replace('O', '0')}"
                    found.setdefault(rid, set()).update(row_keys(line))
            for link in self.activity.links:
                # catalog rows quote how the record is displayed in the evidence captured just before
                ref = link.display_ref.strip().lower()
                if not ref or abs((link.time - doc.captured_at).total_seconds()) > 86400:
                    continue
                pattern = re.compile(r"(?<![a-z0-9])" + re.escape(ref) + r"(?![0-9])")
                hits = [line for line in lines if pattern.search(line.lower()) or pattern.search(line.lower().replace(" ", ""))]
                if hits:
                    ctx = set()
                    for line in hits:
                        ctx |= row_keys(line)
                    found.setdefault(link.resource_id, set()).update(ctx)
            has_pii = bool(EMAIL_RE.search(text)) or any(k.startswith("phone:") for k in doc_keys)
            lower = text.lower()

            header = " ".join([l for l in lines if l.strip()][:4])
            for rid, ctx in found.items():
                system = system_for_resource(rid)
                if not system:
                    continue
                # A document only speaks for its own subject about the record it is *about*
                # (named in its header); other ids are tied to whoever shares their line.
                about_self = rid in header.replace("·", " ")
                keys = ctx | (single_subject_keys if about_self else set())
                flags = {}
                if system == "integration_service":
                    flags["enabled"] = not any(w in lower for w in ("disabled", "paused", "stopped"))
                if system == "backup_service":
                    flags["restore_allowed"] = not any(w in lower for w in ("restore blocked", "restore_allowed false",
                                                                             "deny", "blocked"))
                m = re.search(r"retain until\s+(\d{1,2} \w{3} \d{4})", text, re.IGNORECASE)
                if m and system == "security_service":
                    flags["retention_until"] = datetime.strptime(m.group(1), "%d %b %Y").strftime("%Y-%m-%dT23:59:59Z")
                rtype = None
                path = self.evidence.files.get(doc.file_id, {}).get("file_path", "")
                if system == "support_platform":
                    rtype = "SUPPORT_ATTACHMENT" if "attachment" in path else "SUPPORT_MESSAGE"
                pii = {"document_identifiers": "present"} if has_pii and system not in (
                    "security_service", "backup_service", "integration_service") else {}
                out.append(Observation(
                    file_id=doc.file_id, captured_at=doc.captured_at, obs_time=doc.captured_at, system=system,
                    resource_id=rid, present=True, store="document", pii=pii,
                    link_keys=keys, record_type=rtype, flags=flags, kind="document",
                    collection=f"{doc.file_id}:document"))
        return out

    # ------------------------------------------------------------------ identity
    def _strong(self, keys: set) -> set:
        return {k for k in keys if not k.startswith("name:") and k not in self.ambiguous_keys}

    def _all_time_owners(self) -> dict[str, set]:
        owners = defaultdict(set)
        for o in self.all_observations:
            owners[o.resource_id] |= self.identity.owners_of(self._strong(o.link_keys))
        for link in self.activity.links:
            owners[link.resource_id] |= self.identity.owners_of(self._strong(link.keys))
        return owners

    def _add(self, case: CaseContext, rid: str, basis: str, detail: str):
        system = system_for_resource(rid) or ""
        link = self.links[case.case_id].get(rid)
        if link is None:
            self.links[case.case_id][rid] = Link(rid, system, basis, [detail])
        elif detail not in link.detail:
            link.detail.append(detail)

    def link_direct(self):
        for case in self.cases:
            if not case.authorized or case.subject is None:
                continue
            keys = self._strong(case.keys)
            lo, hi = case.requested_at, case.audit_at
            for o in self.all_observations:
                if lo <= o.obs_time <= hi and o.link_keys & keys:
                    self._add(case, o.resource_id, "document" if o.kind == "document" else "evidence", o.file_id)
            for link in self.activity.links:
                if lo <= link.time <= hi and link.keys & keys:
                    self._add(case, link.resource_id, "catalog", link.activity_id)

    # ------------------------------------------------------------------ workflow
    def assign_workflow(self):
        """Attach deletion-worker events to the request whose reporting slot they belong to.

        Constraints: event time inside the request's slot window for its event kind; a primary
        account submission's result must equal the reported workflow status; one resource per
        system per request; resources already tied to some other subject are never reassigned.
        Remaining ties go to snapshot-order alignment, then a deterministic guess.
        """
        active = [c for c in self.cases if c.authorized and c.subject is not None]
        user_case = defaultdict(list)
        for c in active:
            user_case[c.subject.user_id].append(c)

        def systems_of(case):
            return {system_for_resource(r) for r in self.links[case.case_id]}

        pending = []
        for a in self.activity.workflow:
            kind = wf_kind(a)
            lo, hi = WINDOWS[kind]
            cands = [c for c in active if c.reported_at + lo * HOUR <= a.time <= c.reported_at + hi * HOUR]
            if kind == "account":
                cands = [c for c in cands if STATUS_RESULT.get(c.reported_status) == a.result]
            owners = self.owners.get(a.resource_id, set())
            if owners:
                owned = [c for c in cands if c.subject.user_id in owners]
                if owned:
                    for c in owned:
                        self._add(c, a.resource_id, "workflow", a.activity_id)
                continue  # belongs to an identified subject: never give it to someone else
            if any(a.resource_id in self.links[c.case_id] for c in cands):
                continue
            pending.append((a, kind, cands))

        assigned_event: dict[str, str] = {}
        changed = True
        while changed:
            changed = False
            for a, kind, cands in pending:
                if a.activity_id in assigned_event:
                    continue
                live = [c for c in cands if a.system not in systems_of(c)]
                if len(live) == 1:
                    self._add(live[0], a.resource_id, "workflow", a.activity_id)
                    assigned_event[a.activity_id] = live[0].case_id
                    changed = True

        remaining = [(a, kind, [c for c in cands if a.system not in systems_of(c)])
                     for a, kind, cands in pending if a.activity_id not in assigned_event]
        remaining = [(a, k, cs) for a, k, cs in remaining if cs]
        self._resolve_ties(remaining, assigned_event, systems_of)

    def _bundle_orders(self) -> list[list[tuple[str, int | None]]]:
        """Record sequences from snapshot bundles that are demonstrably listed in subject order."""
        cols = defaultdict(list)
        for o in self.evidence.observations:
            if o.kind.startswith("bundle:") and "operational_record_history" not in o.kind:
                cols[o.collection].append(o)
        orders = []
        for col in cols.values():
            col.sort(key=lambda o: o.position)
            seq = []
            for o in col:
                owners = self.identity.owners_of(self._strong(o.link_keys))
                seq.append((o.resource_id, min(int(u.split("_")[1]) for u in owners) if owners else None))
            known = [n for _, n in seq if n is not None]
            if len(known) >= 2 and all(x < y for x, y in zip(known, known[1:])):
                orders.append(seq)
        return orders

    def _resolve_ties(self, remaining, assigned_event, systems_of):
        """Snapshot-order alignment, then a deterministic guess for primary-account ties only."""

        def unum(c):
            return int(c.subject.user_id.split("_")[1])

        def had_failed_followup(case) -> bool:
            for link in self.links[case.case_id].values():
                for detail in link.detail:
                    act = self.activity.by_id.get(detail)
                    if act is not None and act.source == "deletion_worker" and wf_kind(act) == "followup":
                        return True
            return False

        cand = {}
        for a, kind, cs in remaining:
            seen = self.obs_by_resource.get(a.resource_id, [])
            in_window = [c for c in cs if any(c.requested_at <= o.obs_time <= c.audit_at for o in seen)] or cs
            # The audit snapshot taken just before a request's cutoff covers that request's batch.
            in_batch = [c for c in in_window
                        if any(c.audit_at - 30 * HOUR <= o.captured_at <= c.audit_at for o in seen)] or in_window
            if kind == "success":
                # A run that reported this policy action as completed is a run whose actions were
                # not left failing: requests with failed/pending follow-ups are the less likely owners.
                clean = [c for c in in_batch if not had_failed_followup(c)]
                in_batch = clean or in_batch
            cand[a.activity_id] = (a, kind, in_batch)
        rid_event = {a.resource_id: a.activity_id for a, _, _ in remaining}
        orders = self._bundle_orders()

        def live(aid):
            a, kind, cs = cand[aid]
            return [c for c in cs if a.system not in systems_of(c)]

        progress = True
        while progress:
            progress = False
            # order constraints: unknown record between known neighbours, and unknowns keep relative order
            narrowed = {aid: live(aid) for aid in cand if aid not in assigned_event}
            for seq in orders:
                for i, (rid, num) in enumerate(seq):
                    aid = rid_event.get(rid)
                    if num is not None or aid not in narrowed:
                        continue
                    lo = max([n for _, n in seq[:i] if n is not None], default=0)
                    hi = min([n for _, n in seq[i + 1:] if n is not None], default=10 ** 9)
                    narrowed[aid] = [c for c in narrowed[aid] if lo < unum(c) < hi] or narrowed[aid]
                unknown = [rid_event[r] for r, n in seq if n is None and rid_event.get(r) in narrowed]
                for x, y in zip(unknown, unknown[1:]):
                    if narrowed[x] and narrowed[y]:
                        ymax = max(unum(c) for c in narrowed[y])
                        xmin = min(unum(c) for c in narrowed[x])
                        narrowed[x] = [c for c in narrowed[x] if unum(c) < ymax] or narrowed[x]
                        narrowed[y] = [c for c in narrowed[y] if unum(c) > xmin] or narrowed[y]
            for aid, cs in narrowed.items():
                if len(cs) == 1:
                    a = cand[aid][0]
                    basis = "alignment" if len(live(aid)) > 1 else "workflow"
                    self._add(cs[0], a.resource_id, basis, aid)
                    assigned_event[aid] = cs[0].case_id
                    progress = True
                    if basis == "alignment":
                        self.diagnostics.append({"case_id": cs[0].case_id, "resource_id": a.resource_id,
                                                 "basis": "alignment"})
                    break

        # Every deletion request has exactly one primary account, so an account tie is a true
        # one-of-k choice: pair events (time order) with candidates (subject order). Other record
        # types are paired only when the tie is a perfect matching (as many indistinguishable
        # events as candidate requests), so no request receives a record it may not have.
        groups = defaultdict(list)
        for aid, (a, kind, cs) in cand.items():
            if aid in assigned_event:
                continue
            ls = live(aid)
            if ls:
                groups[(kind, a.system, tuple(sorted(c.case_id for c in ls)))].append(a)
        for (kind, _system, case_ids), events in sorted(groups.items()):
            if kind != "account" and len(events) != len(case_ids):
                continue
            events.sort(key=lambda a: a.time)
            cases = sorted((self.by_case[c] for c in case_ids), key=unum)
            for a in events:
                free = [c for c in cases if a.system not in systems_of(c)]
                if not free:
                    break
                self._add(free[0], a.resource_id, "tie_guess", a.activity_id)
                assigned_event[a.activity_id] = free[0].case_id
                self.diagnostics.append({"case_id": free[0].case_id, "resource_id": a.resource_id,
                                         "basis": "tie_guess", "candidates": list(case_ids)})

    def run(self) -> dict[str, dict[str, Link]]:
        self.link_direct()
        self.assign_workflow()
        return self.links
