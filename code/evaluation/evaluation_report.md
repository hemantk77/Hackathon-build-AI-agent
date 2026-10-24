# Evaluation Report — Ghost Data Still Exists (second pass)

All numbers come from the commands in [Reproduction](#reproduction), run on the final code.

- **No hidden answers were available or used.** Public-sample accuracy, custom-suite accuracy and the internal consistency of the 518-case output are separate measurements and are reported separately.
- "Baseline" means the first-pass implementation (submission v1, `output.csv` SHA-256 `1fc4a7fe…`). That implementation was preserved unchanged and re-run for every old-vs-new comparison below.
- The final output has SHA-256 `dd65f880…`.

## 1. Metrics

The scorer is `code/evaluation/main.py`. It ignores JSON key order but respects array order where the metric says so.

| Metric | Definition |
|---|---|
| Status accuracy | Share of cases whose `deletion_status` matches. |
| Exact-case accuracy | Status and the full ordered step list (all 7 fields) match exactly. |
| Step P / R / F1 | Multiset match on `(phase, system_id, resource_id, operation, state, evidence_id)`, ignoring `step_no`. |
| Field accuracy | Position-by-position agreement of all 7 fields over `max(len(pred), len(gold))` positions. A missing step shifts every later position, so one omission can cost many fields. |
| Sequence accuracy / LCS | Exact match / longest-common-subsequence ratio of the ordered `(phase, operation, system_id, resource_id)` keys. |

## 2. Public sample (32 cases) — baseline vs. improved

| Implementation / link policy | Status | Exact case | Step P | Step R | Step F1 | Field | Sequence | LCS |
|---|---|---|---|---|---|---|---|---|
| Baseline (v1) | 1.0000 | 0.8438 | 0.9895 | 0.9741 | 0.9817 | 0.9674 | 0.8438 | 0.9639 |
| **Improved, `no-guess` (default)** | **1.0000** | **0.8750** | **1.0000** | **0.9793** | **0.9895** | 0.9578 | **0.8750** | **0.9743** |
| Improved, `full` (also pairs genuine ties) | 1.0000 | 0.8750 | 0.9947 | 0.9793 | 0.9869 | 0.9682 | 0.8750 | 0.9743 |
| Improved, `corroborated` (direct + strong links only) | 1.0000 | 0.3438 | 1.0000 | 0.8756 | 0.9337 | 0.7757 | 0.3438 | 0.7973 |

Exact-case and step metrics are reported separately on purpose: 4 of 32 cases are still not exact, even though step F1 is 0.99.

### 2.1 The five baseline mismatches

| Case | Expected vs predicted status | Baseline difference | Root cause | Correction | Final |
|---|---|---|---|---|---|
| case_03 | COMPLETE / COMPLETE | Step 3 `resource_id`: `analytics_5589` instead of `analytics_9406` (1 of 21 fields; evidence, order and numbering correct) | Two indistinguishable anonymize events in one reporting slot (case_03 and eval case_44), paired by coin flip. | Learned **run cadence**: consecutive policy actions of one deletion run are 390 s or 449 s apart (values learned from directly linked runs). `analytics_5589` sits exactly 390 s before case_44's own support redaction, so `analytics_9406` falls to case_03 by exclusion. | **Exact** |
| case_04 | COMPLETE / COMPLETE | Missing `VERIFY_RECORD_ABSENT account_service account_004 evidence_54`; the remaining step shifts, giving 12 field mismatches | `account_004` appears in **no** participant file: no evidence row, activity row, PDF or OCR text. | None possible without inventing a resource ID. | Unchanged (unsupported) |
| case_18 | INCOMPLETE / INCOMPLETE | Missing `VERIFY_RECORD_PRESENT security_service audit_record_6645`; later positions shift (19 field mismatches); findings and remediation correct | `audit_record_6645` appears nowhere; the subject (user_50) has no security record anywhere. | None possible. | Unchanged (unsupported) |
| case_20 | INCOMPLETE / INCOMPLETE | Missing `VERIFY_RECORD_PRESENT security_service audit_record_5569`; 11 field mismatches | `audit_record_5569` appears nowhere; user_48 has no security record. The digits match case_18's `support_5569` and ticket `CS-5569`, which are unrelated collisions. | None possible. | Unchanged (unsupported) |
| case_23 | INCOMPLETE / INCOMPLETE | Baseline guessed `account_7015` for `account_410` (1 field) | A genuine **three-way tie**: `account_410`, `account_7015` and `account_9155` (all FAILED, same slot) for case_23 / case_547 / case_548. None of the three appears in any evidence. | Under the default, no account is asserted. The account step is missing, so the three later positions shift (15 field mismatches), but no wrong resource is claimed. With `--link-policy full` the guess returns (1 field, wrong). | Still ambiguous |

### 2.2 The three "missing" reference records

Each was searched for as a full ID and as its bare digits, across:
- all CSVs;
- the SQL text and the parsed rows;
- JSON, including nested fields;
- log lines and traces;
- PDF text (pypdf);
- the OCR text of all 11 screenshots.

Parser coverage was 94/94 files with no failures.

- **`account_004` (case_04, gold cites `evidence_54`).** Not in `evidence_54`, whose failover and primary tables list `account_005`, `8741`, `9116` and `7204`, nor anywhere else. The gold step relies on information that is not participant-visible. Genuinely unsupported.
- **`audit_record_6645` (case_18).** Only unrelated `account_6645` (February) exists. Genuinely unsupported.
- **`audit_record_5569` (case_20).** Only `support_5569` (case_18's support ticket) and `CS-5569` (ticket of `support_6569`) exist. Genuinely unsupported.

## 3. Ambiguous identity and resource assignments

### 3.1 Confidence classes (defined in `ghost_audit/linker.py`)

| Class | Definition |
|---|---|
| **direct** | An exact identifier of the subject (current or historical email, email hash, phone, `user_id`) on the record or its lookup trace, within `[requested_at, audit_at]`. Or a catalog row naming the subject that the record itself does not contradict with another known customer's identifiers. |
| **strong** | A deletion-worker event that is the only candidate in exactly one request's reporting slot, after excluding requests that already hold a directly linked record of that system. The record must also appear in that request's audit-time evidence. That gives two independent sources. |
| **weak** | Any other workflow inference: exclusivity propagation, run cadence, clean-run filter, evidence-coverage consistency, or an uncorroborated unique slot. |
| **unresolved** | A tie the evidence cannot break. |

### 3.2 What workflow metadata is and is not used for

- **Legitimacy.** Deletion-worker events name resources but no subject. They are emitted in the request's reporting slot (accounts about 1h before `reported_at`). The primary-account submission's result mirrors the reported workflow status in all 24 public cases that have such an event. Both signals are used **only as linkage clues**.
- **State.** Neither `reported_status` nor `reported_result` is ever used as evidence of a record's state. State comes only from evidence observations (`state.py`).
- **When the signal is absent or misleading.** The record is simply not linked: a verification step goes missing, but no state or status is invented. Records already tied by an identifier to another subject are never reassigned.
- **Measured effect.** The status of all 508 deletion requests depends only on **direct** links. The `corroborated` policy, which removes every workflow inference, changes **0** statuses on the 518 cases. Workflow inference contributes only verification steps:

| Policy (full dataset) | Output steps | Steps on weak/unresolved links | Status changes vs default |
|---|---|---|---|
| `corroborated` | 2,912 | 0 (0.0%) | 0 |
| **`no-guess` (default)** | **3,127** | **215 weak (6.9%)** | — |
| `full` | 3,248 | 10.3% (adds unresolved pairings) | 0 |

### 3.3 Audit of the baseline's coin-flip assignments (eval cases)

The baseline paired 137 eval-set records by coin flip (102 accounts, 35 analytics). After the second pass:

| Record type | Now resolved, same request | Now resolved, different request (baseline was wrong) | Still a genuine tie (not asserted by default) |
|---|---|---|---|
| Accounts (102) | 3 (evidence coverage) | 2 (case_191 ↔ case_192, evidence coverage) | 97 |
| Analytics (35) | 10 (run cadence 6, clean run 3, exclusion 1) | 5 (run cadence 2, clean run 2, exclusion 1) | 20 |

The baseline also left 47 anonymize events unassigned. Now 7 events remain unassignable without a guess (5 analytics, 2 legal holds), and they are listed in `diagnostics_summary.md`.

Across the final event log of 1,466 deletion-worker events:
- **direct:** 1,039 owned by an identified subject, plus 19 that belong to another identified subject and are never reassigned;
- **strong:** 38;
- **weak:** 235;
- **paired-but-excluded genuine ties:** 122 (98 accounts in 2- or 3-way ties, 24 analytics);
- **unassignable:** 7;
- **no request with a free slot:** 6.

### 3.4 The weak resolvers, measured

Each resolver below was switched off individually on the public sample, under the default policy.

| Resolver | What it encodes | Public sample without it | Status |
|---|---|---|---|
| Run cadence (learned: 390 s, 449 s) | Consecutive policy actions of one run are spaced by a recurring interval. | exact 0.8438 (−0.031), F1 0.9869 | Kept (weak). Resolves 4/4 public analytics ties correctly. |
| Clean-run filter | A *successful* anonymization belongs to a run without failed or pending follow-ups. | exact 0.7500 (−0.125), F1 0.9788 | Kept (weak). |
| Evidence-coverage consistency | In an account tie, the explicitly checked account (for example a 404 lookup) belongs to the clean-run request and the unchecked one to the request with failed follow-ups. Applied only when that partition yields exactly one pairing. | exact 0.8125 (−0.063), F1 0.9842 | Kept (weak). Consistent with all 9 accounts of public batch 2026-09-15; fixes the case_28/29 tie. |
| Snapshot (bundle) record order | Bundles list collections in a consistent subject order. | exact 0.8750 (±0), F1 0.9895 | **Off by default** (`--use-bundle-order`). No public-sample benefit; only 3 eval records depended on it. |

Never used: `case_id` numbering, event-time order versus subject order (measured at about 50/50 concordance), and readback-log adjacency. Adjacency would have assigned `analytics_5589` to case_03, which the public answer contradicts.

## 4. Screenshot/catalog conflict (case_63) and catalog conflict handling

**Evidence collected:**
- The screenshot `evidence_60` (captured 2026-09-16 07:20) was inspected visually. It shows `marketing_001 · sj.park@naver.com · +82 10-5837-9451` (Soo-jin Park, South Korea, "Live"), last refreshed 2026-09-15 23:40 UTC, which is after the requester's reported deletion at 22:20.
- OCR is correct.
- The catalog row `activity_4008` (2026-09-16 07:27) links `marketing_001` to `kwame-mensah@proton.me` and `user_09` (Kwame Mensah, Ghana).
- `sj.park@naver.com` and the Korean phone number match **no** customer in `user_identities.csv` or `user_audit_log.csv`.
- No other evidence mentions `marketing_001`.

**Determination.**
- This is not an OCR failure, and it is not a false join to another *known* customer.
- The screenshot and catalog genuinely contradict each other, and no participant data can settle it.
- The other 11 catalog rows are each corroborated by their evidence.

**Rule implemented (general, not case-specific):**
- A catalog link is **rejected** when the record's own identifiers belong to a different *known* customer.
- When those identifiers match nobody, the catalog link is **kept and flagged** as an unresolved conflict in diagnostics.

The rule is tested two ways:
- custom case cust_06 (another known customer, so the link is rejected; the baseline wrongly reported INCOMPLETE);
- unit test `test_case_63_catalog_conflict_is_kept_and_flagged`.

The second-pass audit also found a false conflict on case_50. OCR had glued `user_20-analytics_7438-` onto the e-mail address. The OCR normalization now splits glued identifiers (unit-tested), and case_50 is correctly unflagged.

## 5. Assumptions challenged

| Assumption | Classification | Finding | Change |
|---|---|---|---|
| Backups in screenshots ("no visible block ⇒ restorable") | Was a default assumption; now an evidence-supported inference | Restore is now asserted only when the document is a restore console listing the archive (restore operations shown) and the archive's row carries no block marker. A plain listing gives *unknown*. Affects one case (case_55, Vault Recovery Manager). | Positive indicators required (unit-tested) |
| Connectors in screenshots | Evidence-supported inference | Active only when the connector's **own row** shows a streaming indicator ("Continuous", delivery figures). Previously any page without "disabled" counted. Affects case_39, whose row shows Continuous and 1,284 events/hour. | Row-level indicators (unit-tested) |
| Absence by omission | Inference, tightened | Query-style exports (point lookups) can no longer prove absence. Only snapshot captures can. A capture may *override* an explicit "present" only if it was taken for this audit (within 30h of `audit_at`). Public case_05 shows why: present in the account replica, merely unlisted in another batch's later inventory. Pure omission (no explicit statement) uses the latest post-workflow snapshot and is labelled `omission` in diagnostics. | 140 omission states, 1 override (case_126). Case_191 no longer cites a query export (cust_07 fixture) |
| Expired security retention ⇒ delete | Rule-derived inference | **Unexercised**: every `retention_until` in the data is 2031–2034. | None |
| Hash-only analytics contact record ⇒ delete (secondary identifier) | Evidence-supported; confirmed by public case_12 | Only one such record exists in all evidence, and it belongs to sample case_12. | None |
| Evidence freshness | Requirement + one inference | **Requirement:** statements dated after `audit_at` are ignored, and citations must be captured at or before `audit_at`. **Inference** (confirmed by public case_09, whose gold lists records found only in a log exported after the cutoff): a pre-cutoff line inside a post-cutoff file may link records and inform state but is never cited. Measured: 0 conflicts between late and citable evidence. 178 states rest only on late files, and all are *compliant* states (none is a finding or a citation). | Guarded by cust_08 and unit tests |
| Workflow statuses and results as proof | Excluded (requirement) | Never used as state evidence; linkage only (§3.2). | — |

## 6. Custom evaluation cases — baseline vs. improved

The fixtures are built by `code/evaluation/custom_cases/build_custom_cases.py`. The data is fictional; expected answers were written by hand from the contract, not generated. They demonstrate behaviours; they are not evidence of hidden-answer accuracy.

| Case | Failure mode | Expected behaviour (why it follows from the contract) | Baseline | Improved |
|---|---|---|---|---|
| cust_01 | Historical email + `.jr` decoy | Only the old-email search hit is the subject's; exact-match identity only. | pass | pass |
| cust_02 | Post-audit recreation | A snapshot captured after `audit_at` cannot change the answer: COMPLETE, citing the pre-audit file. | pass | pass |
| cust_03 | Replica drift | A replica copy is a remaining record: INCOMPLETE. | pass | pass |
| cust_04 | Spanish data-copy request refusing deletion | No deletion authorized: NOT_APPLICABLE `[]`. | pass | pass |
| cust_05 | Tombstone with PII + active connector + restorable backup | Ordered findings, then disable → block → redact, then 5 verifications. | pass | pass |
| cust_06 | Conflicting identity evidence | The catalog points at a ticket carrying another known customer's e-mail: false join, so COMPLETE for the requester. | **fail** (INCOMPLETE, reports the other customer's PII) | pass |
| cust_07 | Partial capture | A query export that never looked the account up cannot override an explicit 200: INCOMPLETE. | **fail** (COMPLETE) | pass |
| cust_08 | Post-cutoff evidence file | The late log's pre-cutoff 404 links the account; its post-cutoff "restore blocked" line is ignored; the finding cites the pre-cutoff inventory. | pass | pass |
| cust_09/10 | Ambiguity resolved by exclusion | One account is identified by e-mail, so the other is attributed by exclusion (weak). | pass | pass |
| cust_11/12 (`suite_ambiguous`, policy no-guess) | Genuine tie | Two indistinguishable account events and no evidence: no account step is asserted. | **fail** (asserts guessed accounts) | pass |

| Suite | Baseline exact / F1 | Improved exact / F1 |
|---|---|---|
| `suite` (10 cases) | 0.800 / 0.827 | **1.000 / 1.000** |
| `suite_ambiguous` (2 cases, no-guess) | 0.000 / 0.889 | **1.000 / 1.000** |

**Which improvements are robust and which are heuristic:**
- **Robust, contract-driven:** catalog-conflict rejection, query-versus-snapshot scopes, the override window, row-level screenshot indicators, the OCR glue fix, and not asserting ties.
- **Heuristic, workflow/timing-based:** run cadence, clean-run filter and evidence coverage. Each is labelled `weak` in diagnostics, measured in §3.4, and never decides a status.

## 7. Unit tests and the independent validator

`python -m unittest discover -s code/tests`: **31 tests, all passing** (15 first-pass + 16 second-pass). The second-pass tests cover:
- timestamps (offsets, inclusive cutoff, one second after);
- identity-link uniqueness (shared identifiers never link; exact email resolution);
- evidence-reference validity (unknown or late ids rejected; activity ids accepted);
- ordering (data-flow and restore blocks precede record changes; string ordering of resource ids);
- partial captures (query versus snapshot; an old filtered capture cannot override);
- screenshot indicators and OCR glue;
- case_63 conflict flagging;
- status never depending on weak links;
- tie labelling and its exclusion by default;
- false-join rejection.

`code/validate_output.py` re-reads the raw CSVs and shares no code with the pipeline (checks unchanged from v1; all pass).

## 8. Full-dataset run (518 cases) — internal checks only

| Check | Result |
|---|---|
| Rows / unique ids / sorted | 518 / 518 / yes |
| `validate_output.py` | **VALID** (0 violations) |
| Statuses | 153 COMPLETE, 355 INCOMPLETE, 10 NOT_APPLICABLE (identical to baseline) |
| vs baseline | 0 status changes. 120 cases differ only in verification steps: 128 removed (99 account, 29 analytics, mostly coin-flip pairings) and 12 added (10 analytics, 2 account). |
| Status dependence | All 508 deletion statuses depend only on direct links |
| Steps | 3,127. On direct links: 2,877; strong: 35; weak: 215 (6.9%); unresolved: 0 |
| Determinism | Re-runs byte-identical; the packaged code re-run from a clean extraction reproduces the same SHA-256 |
| Evidence coverage | 94/94 files, no parser failures: 24 SQL, 28 JSON, 26 logs (7 formats), 1 text, 4 PDF, 11 PNG (cached OCR). This gives 2,893 observations. |
| Catalog conflicts | 1 genuine (case_63, kept and flagged); 0 rejected |

## 9. Failures found and improvements made

**First pass** (summary):
- seven-format log tokenization;
- scope-only files;
- workflow-slot linking (sample exact 0.34 → 0.66);
- guessing restricted to accounts;
- screenshot over-linking;
- late-file citation fallback;
- citation after `audit_at` (caught by the validator);
- 404 rows counted as present;
- clean-run filter (exact 0.75 → 0.84);
- perfect-matching pairing;
- multilingual refusals.

**Second pass:**

| # | Defect | Found by | Fix | Effect |
|---|---|---|---|---|
| 12 | Analytics ties paired by coin flip (case_03 lost) | Mismatch analysis | Learned run cadence | case_03 exact; 4/4 public analytics ties resolved |
| 13 | Account tie case_191/192 paired against the evidence pattern | Citation inconsistency (case_191 cited an export that never mentions its account) | Evidence-coverage consistency (weak) | 5 eval account ties resolved; case_28/29 now resolved by evidence rather than luck |
| 14 | Query exports treated as proof of absence | Assumption audit | Scope kinds (snapshot vs query) | cust_07 passes; case_191 citation fixed |
| 15 | First attempt at the fix over-reached: a 30h window dropped case_02; using `reported_at` alone flipped case_05 to COMPLETE | Public regression | Split rule: override needs an audit-time capture; pure omission may use a post-workflow capture | Public metrics restored; case_05 correct |
| 16 | Coin-flip ties written into `output.csv` as facts | Brief + ambiguity audit | Default policy `no-guess`; `full` and `corroborated` selectable; every link carries a confidence class | 0 unresolved steps in output; public F1 0.9817 → 0.9895, precision 1.0000 |
| 17 | Catalog row accepted even when the record shows another known customer | cust_06 | Conflict check; reject false joins, flag unknowns | cust_06 passes; case_63 flagged |
| 18 | OCR glued identifiers into e-mails (false conflict on case_50) | Conflict review | Split glued ids before e-mail extraction | case_50 unflagged |
| 19 | Screenshot connector/backup state from page-level absence of words | Assumption audit | Row-level positive indicators | Unit-tested; case_39 and case_55 unchanged on positive evidence |
| 20 | Snapshot-order resolver had no measurable value | Ablation | Off by default (`--use-bundle-order`) | 3 eval records left as recorded ambiguity |
| 21 | Unclosed sqlite connections (ResourceWarnings) | `-W always` test run | Close connections | Clean test output |

## 10. Limitations and decisions for review

- **Unsupported references:** 3 public reference records (`account_004`, `audit_record_6645`, `audit_record_5569`) do not exist in participant data.
- **Genuine ties:** under the default, 97 eval account events and 24 analytics events are not asserted, and 7 more are unassignable. Each case then lacks one verification step that the hidden answer probably contains.
  - `--link-policy full` restores deterministic pairings. On the public sample it gives the same exact-case score (0.875), better field accuracy (0.968 vs 0.958), lower precision (0.9947) and lower F1 (0.9869).
  - On the hidden set, `full` should gain exact-case matches on correctly guessed ties, at the cost of asserting about 50–67% wrong associations among them.
  - **This choice is the user's.**
- **case_63:** follows the uncontradicted catalog link. If the screenshot is taken as authoritative instead, the requester has no evidenced record at all.
- **Hand-crafted screenshot/PDF cases (12):** each links only the catalogued record. There are no public examples for them.

## Reproduction

```bash
python code/main.py --diagnostics diag.json --summary code/evaluation/diagnostics_summary.md
python code/validate_output.py
python code/evaluation/main.py --verbose
python code/evaluation/main.py --link-policy full
python code/evaluation/custom_cases/build_custom_cases.py
python code/evaluation/main.py --custom --verbose
python -m unittest discover -s code/tests
```
