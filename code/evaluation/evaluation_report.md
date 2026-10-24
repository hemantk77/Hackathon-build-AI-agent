# Evaluation Report — Ghost Data Still Exists (final review)

All numbers come from the commands in [Reproduction](#reproduction), run on the final code.

- **No hidden answers were available or used.** Public-sample accuracy, custom-suite accuracy and the internal consistency of the 518-case output are separate measurements and are reported separately. Nothing here claims that the official grader has been passed.
- **Implementations compared:**
  - "v1" is the first-pass implementation (`output.csv` SHA-256 `1fc4a7fe…`).
  - "second pass" is the implementation before this final review (`output.csv` `dd65f880…`).
  - Both were preserved unchanged and re-run for every comparison below.
- **The final output is `dd65f880…`**, byte-identical to the second pass. The final review changed:
  - how completion is decided;
  - how findings choose their evidence;
  - packaging and reproducibility.

  None of these changes moved any public or eval answer under the default settings (§2, §6).

## 1. Metrics

The scorer is `code/evaluation/main.py`. It ignores JSON key order but respects array order where the metric says so.

| Metric | Definition |
|---|---|
| Status accuracy | Share of cases whose `deletion_status` matches. |
| Exact-case accuracy | Status and the full ordered step list (all 7 fields) match exactly. |
| Step P / R / F1 | Multiset match on `(phase, system_id, resource_id, operation, state, evidence_id)`, ignoring `step_no`. |
| Field accuracy | Position-by-position agreement of all 7 fields over `max(len(pred), len(gold))` positions. A missing step shifts every later position, so one omission can cost many fields. |
| Sequence accuracy / LCS | Exact match / longest-common-subsequence ratio of the ordered `(phase, operation, system_id, resource_id)` keys. |

## 2. Public sample (32 cases)

| Implementation / setting | Status | Exact case | Step P | Step R | Step F1 | Field | Sequence | LCS |
|---|---|---|---|---|---|---|---|---|
| v1 | 1.0000 | 0.8438 | 0.9895 | 0.9741 | 0.9817 | 0.9674 | 0.8438 | 0.9639 |
| Second pass, `no-guess` | 1.0000 | 0.8750 | 1.0000 | 0.9793 | 0.9895 | 0.9578 | 0.8750 | 0.9743 |
| **Final, `no-guess` (default)** | **1.0000** | **0.8750** | **1.0000** | **0.9793** | **0.9895** | **0.9578** | **0.8750** | **0.9743** |
| Final, `full` (also pairs genuine ties) | 1.0000 | 0.8750 | 0.9947 | 0.9793 | 0.9869 | 0.9682 | 0.8750 | 0.9743 |
| Final, `corroborated` (direct + strong links only) | 1.0000 | 0.3438 | 1.0000 | 0.8756 | 0.9337 | 0.7757 | 0.3438 | 0.7973 |
| Final, `--strict-capture-cutoff` (comparison only, §5) | 1.0000 | 0.6562 | 1.0000 | 0.9275 | 0.9624 | 0.8601 | 0.6562 | 0.9203 |

Exact-case and step metrics are reported separately on purpose: 4 of 32 cases are still not exact, even though step F1 is 0.99.

### 2.1 The remaining public mismatches

| Case | Difference | Root cause | Status |
|---|---|---|---|
| case_04 | Missing `VERIFY_RECORD_ABSENT account_service account_004 evidence_54` | `account_004` appears in **no** participant file: no evidence row, activity row, PDF or OCR text. `evidence_54`'s tables list `account_005`, `8741`, `9116` and `7204`. | Unsupported. No resource id is invented. |
| case_18 | Missing `VERIFY_RECORD_PRESENT security_service audit_record_6645` | Appears nowhere. The subject (user_50) has no security record anywhere. Only an unrelated `account_6645` exists. | Unsupported |
| case_20 | Missing `VERIFY_RECORD_PRESENT security_service audit_record_5569` | Appears nowhere. `support_5569` and ticket `CS-5569` are unrelated digit collisions. | Unsupported |
| case_23 | Missing the account verification | A genuine three-way tie (`account_410`, `account_7015`, `account_9155`, all FAILED, same slot) for case_23 / case_547 / case_548. None of the three appears in any evidence. | Ambiguous. Not asserted under `no-guess`. `full` guesses (wrong here). |

Each missing id was searched for as a full id and as bare digits, across all CSVs, SQL text and parsed rows, nested JSON, log lines, PDF text and the OCR text of all 11 screenshots. Parser coverage was 94/94 files.

The case_01 to case_32 fixes from earlier passes are described in §11.

## 3. Heuristic dependence of the submitted output (`no-guess`)

The ambiguity classes are defined in `ghost_audit/linker.py`:
- **direct:** an exact identifier, or a catalog row the record does not contradict;
- **strong:** a unique reporting slot that is also corroborated by audit-time evidence;
- **weak:** a workflow/timing inference;
- **unresolved:** a tie the evidence cannot break.

Unresolved ties are **not** weak inferences. They are never written under the default.

| Class | Method (evidence basis) | Output steps | Cases |
|---|---|---|---|
| direct | identifiers on the record or its trace; catalog rows; identifier + slot | 2,877 | — |
| strong | unique slot + record present in the request's audit-time evidence | 35 | 34 |
| weak | `slot_unique`: only request in the reporting slot, no audit-time corroboration | 118 | 118 |
| weak | `clean_run`: a successful action belongs to a run without failed follow-ups | 38 | 38 |
| weak | `run_cadence`: chained 390 s / 449 s from the request's own actions | 29 | 29 |
| weak | `slot_exclusion_by_direct_links`: unique after removing requests already holding that system | 21 | 21 |
| weak | `evidence_coverage`: account tie partitioned by which account the audit capture checked | 5 | 5 |
| weak | `slot_exclusion_propagated`: unique after removing other inferred links | 3 | 3 |
| weak | `in_audit_capture`: only one candidate's audit capture contains the record | 1 | 1 |
| **weak, total** | | **215 (6.9%)** | **203** |
| unresolved (excluded) | genuine ties; `full` would add them | 0 written (121 under `full`) | 109 cases have an excluded tie |

Additional measurements:
- Every weak step is a **verification** step. All 508 deletion statuses depend only on direct links.
- `corroborated` (which removes all workflow inference) changes 0 statuses.
- `full` adds 121 steps, all verifications, and changes 0 statuses.
- `no-guess` stays the default: on the public sample `full` has the same exact-case score, lower precision (0.9947) and lower F1 (0.9869).

The evidence does not support switching policy.

## 4. COMPLETE decisions and unknown state (completion guard)

**Audit of the second-pass rule.** The rule was "COMPLETE when no linked record is violating". Measured on the 518 eval cases:

| Question | Result |
|---|---|
| Linked resources whose state at `audit_at` is unknown | 6. All are weak links in INCOMPLETE cases. |
| COMPLETE cases with any unknown-state linked resource | 0 |
| COMPLETE cases missing verification for a linked resource | 0 |
| INCOMPLETE cases with a known violation but no finding evidence captured ≤ `audit_at` | 0 |
| Deletion cases with no linked account | 107 (75 INCOMPLETE, 32 COMPLETE) |
| COMPLETE cases whose primary account is unattributed | 47. In 46 of them, every candidate account in the tie is proven absent. The 47th (case_45) has no account event at all; its only record is a retained audit record. |

**Gap found.** The rule could report COMPLETE while an unattributed record that may be the requester's still existed. The eval data happens not to contain that situation, but the rule allowed it, so this was a latent false-completion risk.

**Schema limitation.** There is no `UNKNOWN` status. The choices for an unestablished case are:
- claim COMPLETE (risking a false completion);
- invent a finding (forbidden);
- report INCOMPLETE with only the checks that must pass.

The last is the most defensible contract-compliant behaviour.

**Rule implemented (planner.py).** A case with no evidenced violation is still not claimed COMPLETE when any of these holds:
1. a direct- or strong-linked record's state at `audit_at` is unknown;
2. a violation is visible only in a file captured after `audit_at` (it cannot be cited);
3. any record in an unattributed tie that the request is part of is not proven compliant.

In those cases the output is INCOMPLETE with verification steps only (empty `evidence_id`, no finding), and a diagnostics note gives the reason. If every tie candidate is proven compliant, the requester's record is compliant whichever candidate it is; the case may then be COMPLETE, and the tie is noted but never asserted. Weak-linked records with unknown state are reported in notes but do not block completion, because they may not be the requester's at all.

The validator now treats a verification-only INCOMPLETE as a warning, not an error. Remediation without a finding remains an error.

**Impact, measured (second pass vs final):**

| Run | Cases changed | Status changes |
|---|---|---|
| Public sample, `no-guess` / `full` / `corroborated` | 0 / 0 / 0 | 0 / 0 / 0 |
| 518 eval cases, `no-guess` / `full` / `corroborated` | 0 / 0 / 0 | 0 / 0 / 0 |
| Custom `suite`, `suite_ambiguous` | 0 | 0 |
| Custom `suite_guard` (new, §8) | 2 | 2 (false COMPLETE → INCOMPLETE) |

Under the default, the guard flags 10 non-compliant tie candidates in 8 eval cases. All 8 are already INCOMPLETE on evidenced findings. In 110 cases the unattributed tie had every candidate proven compliant.

## 5. Evidence timestamps vs the cutoff rule

The literal contract says "use only information available at or before `audit_at`". Two isolated interpretations were compared, with everything else identical:

- **A (default):** a statement whose own timestamp is ≤ `audit_at`, inside a file whose manifest `captured_at` is after `audit_at`, may link records and inform state. It is never cited. Statements timestamped after `audit_at` are always ignored.
- **B (`--strict-capture-cutoff`):** any file captured after `audit_at` is ignored entirely for that request: identity links, record ownership, tie filters, policy flags and state.

| Measure | A | B |
|---|---|---|
| Public exact-case / step F1 / field | 0.8750 / 0.9895 / 0.9578 | 0.6562 / 0.9624 / 0.8601 |
| Public cases that differ from A | — | 8 (no status change) |
| Eval cases that differ from A | — | 126 |
| Eval status changes | — | 2 (case_218, case_219: COMPLETE → INCOMPLETE, completion guard) |
| Eval output steps | 3,127 | 2,983 (−116 audit-record, −26 account, −2 legal-hold steps) |
| Steps citing a file captured after `audit_at` | **0** | 0 |

**Public examples that conflict with the literal whole-file reading.** In 7 public answers, the gold includes a record whose attribution depends on pre-cutoff statements inside a late export. Two late exports are involved:
- `evidence_02`: a snapshot bundle captured 2026-09-17 for a 2026-09-15 audit, whose inner snapshots predate the audit;
- `evidence_06`: a log captured 2026-09-18 for a 2026-09-16 audit, whose lines predate the audit.

The dependence is either direct or indirect:
- **Direct (5 cases).** The record's subject identifier appears only in that late export: case_09 (`audit_record_4902`, `evidence_06`), case_24, 29 and 30 (audit records, `evidence_02`) and case_26 (`account_5684`, `evidence_02`).
- **Indirect (2 cases).** The record itself is visible in pre-cutoff evidence, but the competing request's records are identified only in `evidence_02`, and that is what breaks the tie:
  - case_25: `account_3136` becomes a case_25/case_26 tie once case_26's account is unknown;
  - case_21: `analytics_5335` loses its clean-run tie-break against case_23.

Under B, all 7 lose the record. The eighth difference (case_23) was already inexact.

**Under A, measured:**
- 116 direct links rest only on 16 late-captured files. Their state is used, but never cited.
- 178 resource states rest only on late files. All 178 are *compliant* states, so none produces a finding:
  - 11 are in COMPLETE cases. Each is cited to the audit-time account snapshot, which agrees.
  - 167 are in INCOMPLETE cases, where verification carries no evidence.
- No statement timestamped after `audit_at` is used anywhere (unit-tested; custom cust_02 and cust_08).

**Recommendation (implemented).** Keep A. It is the narrowest reading consistent with every published example:
- the cutoff applies to the time a statement describes;
- the citation rule applies to the file's capture time;
- B contradicts 7 of the 32 published answers.

## 6. Finding citations and COMPLETE verification

Every evidence-bearing step in the final 518-case output was checked by an independent script. The script re-reads the cited file's own statements about the step's resource, timed ≤ `audit_at`.

| Step kind | Supported | Problems |
|---|---|---|
| Findings: the cited structured file shows the violation | 711 | 0 |
| Findings: the cited screenshot/PDF row shows the violation (case_33, 34, 35, 39, 50, 52, 53, 55, 61, 63) | 10 | 0 |
| COMPLETE verifications: the cited file states the compliant state explicitly | 426 (424 structured, 2 document) | 0 |
| COMPLETE verifications: absence by omission from a snapshot of the same system | 41 | 0 |

**Omission-based absence.** All 41 omission citations meet three conditions:
- they come from SQL snapshots of the account store: a full customer-data snapshot (primary + replica tables), or an inventory whose `snapshot_scope` lists `account_service`;
- the snapshot was captured ≤ 1 hour before `audit_at`;
- the snapshot was taken after the workflow reported.

None comes from a query-style export (point lookups), a partial batch inventory of another system, or an unrelated capture. On the public sample the same rule produces 3 COMPLETE omission verifications (case_01 and case_02 via `evidence_54`, case_31 via `evidence_51`), and all 3 match the published answer exactly. The older capture used for case_02 (40 h before audit) is the one the published answer cites.

**Fallback fix.** When a violation's latest citable statement agreed with it, the finding cited that statement. Otherwise the second pass fell back to "the latest citable file showing the record present". For a REDACT/ANONYMIZE record, that file could show the record already redacted. The fallback now requires a citable statement that itself shows the violation. If none exists, the case is not claimed complete and no finding is written. This had no effect on the current output; it is unit-tested.

## 7. Workflow metadata and weak resolvers

- **Linkage only.** Deletion-worker events name resources but no subject. They are emitted in the request's reporting slot (accounts about 1 hour before `reported_at`). The primary-account result mirrors `reported_status` in all 24 public cases that have such an event. Both are used **only as linkage clues**.
- **Never state evidence.** Neither `reported_status` nor `reported_result` is ever used as evidence of state. State comes only from evidence observations (`state.py`).
- **Never reassigned.** Records tied by an identifier to another subject are never reassigned.

Each resolver was switched off individually on the public sample, under the default policy:

| Resolver | Public sample without it | Status |
|---|---|---|
| Run cadence (learned: 390 s, 449 s) | exact 0.8438 (−0.031), F1 0.9869 | Kept (weak). Resolves 4/4 public analytics ties correctly. |
| Clean-run filter | exact 0.7500 (−0.125), F1 0.9788 | Kept (weak) |
| Evidence-coverage consistency | exact 0.8125 (−0.063), F1 0.9842 | Kept (weak). Fixes the case_28/29 tie. |
| Snapshot (bundle) record order | exact 0.8750 (±0) | **Off by default** (`--use-bundle-order`) |

Never used: `case_id` numbering, event-time order versus subject order, and readback-log adjacency (which the public answer for case_03 contradicts).

**Catalog conflicts (case_63).** The screenshot `evidence_60` shows `marketing_001` with another person's e-mail address, phone number and name; those identifiers are withheld from this report. They match no customer in `user_identities.csv` or `user_audit_log.csv`. The catalog row `activity_4008` links `marketing_001` to the requester. The general rule:
- a catalog link is **rejected** when the record's own identifiers belong to a different *known* customer (custom cust_06);
- it is **kept and flagged** when they match nobody (case_63).

## 8. Custom evaluation cases

All fixtures are fictional synthetic data built by `code/evaluation/custom_cases/build_custom_cases.py`:
- They are stored under `<suite>/data/`.
- They contain no challenge evidence, identifiers or hidden labels; a packaging check enforces this (§9).
- The only challenge file they use is the policy `deletion_rules.csv`. It is not shipped and is copied in from the supplied `dataset/` at run time.
- Expected answers were written by hand from the contract. They demonstrate behaviours; they are not evidence of hidden-answer accuracy.

| Case | Failure mode | Expected behaviour | v1 | Second pass | Final |
|---|---|---|---|---|---|
| cust_01 | Historical email + `.jr` decoy | Only the old-email search hit is the subject's | pass | pass | pass |
| cust_02 | Post-audit recreation | A later snapshot cannot change the answer: COMPLETE | pass | pass | pass |
| cust_03 | Replica drift | A replica copy is a remaining record: INCOMPLETE | pass | pass | pass |
| cust_04 | Spanish data-copy request refusing deletion | NOT_APPLICABLE `[]` | pass | pass | pass |
| cust_05 | Tombstone with PII + active connector + restorable backup | Findings, then disable → block → redact, then 5 verifications | pass | pass | pass |
| cust_06 | Catalog row vs another known customer's e-mail | False join rejected: COMPLETE | fail | pass | pass |
| cust_07 | Partial (query) capture | Cannot override an explicit 200: INCOMPLETE | fail | pass | pass |
| cust_08 | Post-cutoff evidence file | Pre-cutoff line links but is not cited; post-cutoff line ignored | pass | pass | pass |
| cust_09/10 | Ambiguity resolved by exclusion | Second account attributed by exclusion (weak) | pass | pass | pass |
| cust_11/12 (`suite_ambiguous`) | Genuine tie, no evidence | No account step asserted | fail | pass | pass |
| **cust_13/14 (`suite_guard`, new)** | Tie where the audit snapshot still holds one of the two unattributed accounts | Neither request may be COMPLETE: INCOMPLETE, verification only, no invented finding | fail | **fail** (both COMPLETE) | **pass** |

| Suite | v1 exact / F1 | Second pass exact / F1 | Final exact / F1 |
|---|---|---|---|
| `suite` (10) | 0.800 / 0.827 | 1.000 / 1.000 | **1.000 / 1.000** |
| `suite_ambiguous` (2, no-guess) | 0.000 / 0.889 | 1.000 / 1.000 | **1.000 / 1.000** |
| `suite_guard` (2, no-guess) | — | 0.000 / 0.000 | **1.000 / 1.000** |

cust_13/14 encode a policy decision (do not claim completion that is not established), not an attribution. Exactly one of the two deletions is in fact complete.

## 9. Packaging and reproducibility

**Defect found.** The second-pass `code.zip` shipped `code/ghost_audit/evidence_cache/` (11 files of screenshot OCR text, derived from challenge evidence and containing fictional personal identifiers). Other copied material was also present:
- a verbatim copy of `dataset/deletion_rules.csv` inside each custom fixture (in folders named `dataset/`);
- one dataset e-mail address in a unit test;
- one dataset e-mail address and OCR-derived identifiers in this report.

`rapidocr-onnxruntime` was marked "optional" because the cache made it unnecessary.

**Fixes:**
- `package_submission.py`:
  - excludes the OCR cache and every other cache;
  - excludes any file byte-identical to a file in `dataset/`, and the fixtures' rules copy;
  - **refuses to build** if a shipped text file contains a dataset identifier: names, emails, phones and email hashes from the identity files and audit log, plus emails found in evidence text, PDFs or the local OCR text.
- Fixture folders were renamed `data/` and fixture paths were kept short. The longest archive path is 85 characters; a longer intermediate naming failed to extract under the Windows 260-character limit.
- The test and report strings were replaced with synthetic or withheld values.
- `requirements.txt` declares all runtime dependencies as required, pinned to the verified versions: `pypdf==6.16.2`, `rapidocr-onnxruntime==1.2.3`, `onnxruntime==1.31.0`, `opencv-python==5.0.0.93`, `numpy==2.2.5`. `anthropic` is listed as a separate optional install.
- A missing OCR install now prints a `WARNING` per unreadable screenshot instead of failing silently.

**Clean-environment reproduction (measured):**
1. Built `code.zip`, extracted it into an empty directory, and confirmed that no OCR cache was present.
2. Supplied `dataset/` separately.
3. Created a fresh `python -m venv` (Python 3.13.0, Windows) and ran `pip install -r code/requirements.txt` from PyPI. It installed exactly the pinned versions.
4. Results:
   - `python code/main.py`: 518 rows, 94/94 evidence files parsed, 0 problems, 0 model calls. 43 s on the first run (fresh OCR), 2.2 s cached.
   - `output.csv` SHA-256: `dd65f880…`, **byte-identical** to the submitted file. The freshly generated OCR text is identical to the original cache.
   - `validate_output.py`: VALID. Public scorer: 0.8750 exact. All three custom suites: 1.000. 43/43 unit tests pass.
   - Without RapidOCR (simulated), the run warns for all 11 screenshots and the output changes (`3de88c35…`). The dependency is genuinely required.

**Archive inspection.** The final archive contains `README.md`, `code/` (source, tests, prompts, synthetic fixtures, reports, `last_run_usage.json` telemetry) and `evaluation/` (the two report copies). It contains no `dataset/`, OCR cache, dataset-identical file, secrets, `.env`, virtual environment, `__pycache__` or nested archive (§10 lists the exact checks).

## 10. Unit tests, validator and full-dataset checks

`python -m unittest discover -s code/tests` runs **43 tests, all passing**:
- 15 first-pass tests;
- 16 second-pass tests;
- 12 final-review tests:
  - the completion guard (tie candidate present, all candidates compliant, strong-link unknown state, weak-link unknown state, `suite_guard`);
  - finding fallback citation (a mention is not enough);
  - a violation visible only in a late file;
  - strict-cutoff mode (public case_26, state from late files);
  - the validator warning;
  - packaging exclusions;
  - shipped files containing no dataset identifier.

`code/validate_output.py` re-reads the raw CSVs and shares no code with the pipeline.

| Full 518-case check | Result |
|---|---|
| Rows / unique ids / sorted | 518 / 518 / yes |
| `validate_output.py` | **VALID**, 0 violations, 0 warnings |
| Statuses | 153 COMPLETE, 355 INCOMPLETE, 10 NOT_APPLICABLE (unchanged) |
| Steps | 3,127: direct 2,877, strong 35, weak 215 (6.9%), unresolved 0 |
| Citations | 1,188 evidence-bearing steps, all supported by the cited file (§6). 0 cite a file captured after `audit_at`. |
| Determinism | Re-runs byte-identical, including from a clean extraction with fresh OCR (§9) |
| Evidence coverage | 94/94 files: 24 SQL, 28 JSON, 26 logs (7 formats), 1 text, 4 PDF, 11 PNG. 2,893 observations. |

## 11. Failures found and improvements made

**First pass** (summary):
- seven-format log tokenization;
- scope-only files;
- workflow-slot linking;
- restricted guessing;
- screenshot over-linking;
- late-file citation fallback;
- citation after `audit_at` (caught by the validator);
- 404 rows counted as present;
- clean-run filter;
- perfect-matching pairing;
- multilingual refusals.

**Second pass** (#12–#21):
- run cadence (case_03 exact);
- evidence-coverage consistency;
- query-versus-snapshot scopes (cust_07);
- split override/pure-omission rule (case_02, case_05);
- default `no-guess` policy (precision 1.0000);
- catalog-conflict rejection (cust_06, case_63);
- OCR glued-id split (case_50);
- row-level screenshot indicators;
- bundle order off by default;
- closed sqlite connections.

**Final review:**

| # | Defect | Found by | Fix | Effect |
|---|---|---|---|---|
| 22 | COMPLETE could be claimed while an unattributed tie candidate still existed, or a corroborated record's state was unknown | COMPLETE-decision audit (§4) | Completion guard; verification-only INCOMPLETE; validator warning | 0 output changes; `suite_guard` false COMPLETE fixed |
| 23 | A finding's fallback citation needed only a mention of the record | Citation audit (§6) | The fallback must show the violation | 0 output changes; unit-tested |
| 24 | Strict cutoff interpretation undocumented and untestable | Cutoff audit (§5) | `--strict-capture-cutoff` comparison mode in linker, state and planner | Interpretation A justified by 7 public answers |
| 25 | OCR cache (challenge-derived text) shipped in `code.zip`; OCR dependency marked optional | Packaging audit | Cache excluded; dependencies required and pinned; loud warning without OCR | Clean-venv reproduction byte-identical |
| 26 | Dataset rules file copied into fixtures, plus dataset identifiers in a test and the report | Identifier scan of shipped files | Rules restored at run time; synthetic or withheld strings; packager refuses copies | 0 dataset identifiers in the archive |
| 27 | Fixture path rename overflowed Windows MAX_PATH on extraction | Clean extraction | Short fixture paths (`data/`, ≤ 85 characters) | Extraction succeeds |
| 28 | Fixture name coincided with a dataset customer name | Identifier scan | Renamed the fixture person | — |

## 12. Limitations and remaining risks

- **Unsupported references.** 3 public reference records (`account_004`, `audit_record_6645`, `audit_record_5569`) do not exist in participant data.
- **Genuine ties.** Under the default, 97 eval account events and 24 analytics events are not asserted, and 7 more are unassignable. Each affected case lacks one verification step that the hidden answer probably contains. `full` would pair them, but most pairings in a 2- or 3-way tie would be wrong.
- **Weak inferences.** 215 verification steps (203 cases) rest on workflow/timing heuristics (§3). They are validated on public ties, but not proven.
- **Cutoff interpretation.** A is supported by the public answers. If the hidden grader applied B, about 144 steps in 126 cases would differ.
- **case_63.** The uncontradicted catalog link is followed; a manual reviewer might treat the screenshot as authoritative.
- **OCR versions.** Only the pinned OCR stack was verified. Other versions could change the 10 screenshot-backed cases.
- **Hand-crafted screenshot/PDF cases (12).** There are no public examples of this kind.

## Reproduction

```bash
python -m pip install -r code/requirements.txt
python code/main.py --diagnostics diag.json --summary code/evaluation/diagnostics_summary.md
python code/validate_output.py
python code/evaluation/main.py --verbose
python code/evaluation/main.py --link-policy full
python code/evaluation/main.py --strict-capture-cutoff
python code/evaluation/custom_cases/build_custom_cases.py
python code/evaluation/main.py --custom --verbose
python -m unittest discover -s code/tests
python code/package_submission.py
```
