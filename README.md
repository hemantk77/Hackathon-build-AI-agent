# Ghost Data Still Exists — Deletion-Audit Agent

HackerRank Orchestrate (October 2026). For every request in `dataset/deletion_requests.csv`, the agent does the following:

1. It decides whether the request actually authorizes deletion.
2. It resolves the subject's current and historical identifiers.
3. It finds every record and data flow that belongs to the subject.
4. It reconstructs each record's state at the case's `audit_at` cutoff.
5. It applies `deletion_rules.csv` to each record.
6. It emits `COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE` with an ordered, evidence-cited `steps_json`.

The full contract is in [`problem_statement.md`](./problem_statement.md) and [`AGENTS.md`](./AGENTS.md).

The production pipeline is **deterministic Python**: the final full run made **0 model calls**. An optional Claude fallback for ambiguous request intent exists, but it is off by default; see [Optional LLM fallback](#optional-llm-fallback).

---

## Quick start

From the repository root:

```bash
python -m pip install -r code/requirements.txt   # pypdf + RapidOCR (all required, pinned)
python code/main.py                               # writes ./output.csv (518 rows)
python code/validate_output.py                    # independent contract validator
python code/evaluation/main.py                    # score the 32 public samples
python code/evaluation/main.py --custom           # score the custom adversarial suite
python -m unittest discover -s code/tests         # unit tests
```

Requirements:

- Python 3.11 or newer. The pinned versions in `code/requirements.txt` were verified on Python 3.13 (Windows, CPU).
- Put the supplied challenge `dataset/` folder at the repository root, or pass `--data-dir`. `code.zip` does not contain it.
- Runtime dependencies:
  - `pypdf` reads the PDF evidence.
  - `rapidocr-onnxruntime` (with `onnxruntime`, `opencv-python` and `numpy`) reads the screenshot evidence. Its OCR models ship inside the wheel.
  - All are required. If OCR is missing, the run prints a `WARNING` for each unreadable screenshot, and the affected steps are lost.
- No network access and no API keys are needed at run time.
- The first run OCRs the 11 screenshots (about 45 seconds on a laptop CPU) and caches the text in `code/ghost_audit/evidence_cache/`. Later runs take about 2 seconds.
  - That cache is derived from the challenge evidence, so it is never packaged.
- The output was reproduced byte-for-byte from `code.zip` in a fresh virtual environment, with the dataset supplied separately and no cache present; see the evaluation report.

Useful flags:

| Command | Purpose |
|---|---|
| `python code/main.py --requests sample_deletion_requests.csv --out sample_predictions.csv` | Audit another request file in `dataset/` |
| `python code/main.py --diagnostics diag.json` | Per case: subject resolution, authorization cues, every linked resource with its link confidence/method/candidates, policy rule, state at `audit_at` with the evidence trail, citation, and notes |
| `python code/main.py --summary summary.md` | Run summary: link confidence counts, share of steps on heuristics, workflow-event outcomes, omission/late-file states, catalog conflicts, coverage |
| `python code/main.py --link-policy {no-guess,full,corroborated}` | Which link confidence classes may produce steps. Default `no-guess` never asserts a genuine tie; `full` also pairs ties deterministically; `corroborated` keeps only direct and strong links |
| `python code/main.py --use-bundle-order` | Also break ties by record order inside snapshot bundles (weak; off by default) |
| `python code/main.py --strict-capture-cutoff` | Comparison mode: ignore every file whose manifest `captured_at` is after `audit_at`, even for linking and state (see "State at `audit_at`") |
| `python code/main.py --data-dir <dir>` | Run against another dataset with the same layout (used by the custom suites) |
| `python code/evaluation/main.py --verbose` | Per-case missing/extra steps against the reference answers |
| `python code/evaluation/custom_cases/build_custom_cases.py` | Rebuild the custom adversarial fixtures |
| `python code/package_submission.py [--out path]` | Build `code.zip`. Excludes `dataset/`, the OCR cache and every other cache, any file byte-identical to a dataset file, secrets and nested archives. Refuses to build if a shipped file contains a dataset identifier |

---

## Architecture

```
code/
  main.py                    CLI entry point
  validate_output.py         independent validator (re-reads raw CSVs, shares no code with the pipeline)
  package_submission.py      builds code.zip
  requirements.txt
  ghost_audit/
    loaders.py               CSV loading, UTC timestamp parsing
    identity.py              current + historical identity index (emails, email hashes, phones, user_id)
    authorization.py         multilingual deletion-intent classifier (negations and non-deletion intents win)
    activity.py              system_activity index: workflow events, catalog links, recreation signals
    evidence/
      log_lines.py           tokenizer for 7 log formats (kv, JSON, syslog, pipe, bracket, cloud-runtime, record_lookup)
      parsers.py             SQL (executed in in-memory sqlite3), JSON (exports, bundles, manifests), logs, handover text
      documents.py           PDF text (pypdf/pdftotext) and screenshot OCR (RapidOCR, cached in evidence_cache/)
      records.py             one interpreter for every record shape -> Observation (presence, PII, refs, flags)
      model.py, registry.py  normalized Observation/Scope types; per-file coverage report
    linker.py                which resources belong to which request (see "Resource discovery")
    policy.py                data category -> rule -> treatment, from deletion_rules.csv
    state.py                 state at audit_at, replica drift, absence by omission, citation choice
    planner.py               findings -> remediation -> verification; COMPLETE vs INCOMPLETE
    output.py                grader ordering (phase, operation table order, system_id, resource_id) and CSV
    diagnostics.py           per-case diagnostics and the run summary (kept outside output.csv)
    llm.py, prompts.md       optional Claude fallback (off by default)
  tests/                     43 unit tests (test_components.py, test_second_pass.py, test_final_review.py)
  evaluation/
    main.py                  scorer (status, exact-case, step P/R/F1, field, sequence, LCS)
    custom_cases/            14 hand-labelled synthetic cases in three suites (+ builder script; the
                             challenge's deletion_rules.csv is copied in from dataset/ at run time)
    evaluation_report.md     metrics, mismatch analysis, ambiguity audit, assumptions, failures and fixes
    usage_report.md          model and token usage of the final run
    diagnostics_summary.md   generated summary of the final run
```

### Pipeline

1. **Evidence indexing.** All 94 manifest files are parsed and every failure is recorded in the coverage report; the final run had 0 failures. Each statement about a resource becomes an `Observation` that carries:
   - the file's manifest `captured_at` (decides whether it may be cited);
   - the statement's own time (decides state: log line time, SQL capture time, bundle inner `captured_at`, row `observed_at`/`recorded_at`);
   - presence (404 / `rows=0` / `NOT_FOUND` = absent);
   - remaining direct identifiers, stable references, and flags (`enabled`, `restore_allowed`, `eligible`, `retention_until`, and so on).

   Captured collections (`snapshot_scope`, bundle collections, full customer-data DB snapshots) also become `Scope`s, so absence can be proven by omission.

2. **Authorization.** Deletion cues are matched in EN, ES, PT, FR, DE, IT, JA, KO and ZH. Explicit refusals ("not asking for deletion", "don't delete", "no eliminen", ...) and non-deletion intents (access/copy, portability, correction, marketing opt-out, login help) override them. Non-deletion requests get `NOT_APPLICABLE` with `[]`.

3. **Identity.** The request email (case-insensitive, current or historical) resolves to exactly one `user_id`. Linking uses only exact normalized strong keys: emails, email hashes (including historical hashes), phones, and `user_N`. Names never link on their own, so look-alikes such as `*.jr@` addresses never match.

4. **Resource discovery** (`linker.py`). Every link carries a confidence class:
   - **direct:**
     - an observation carrying one of the subject's identifiers, observed within `[requested_at, audit_at]`; log `trace_id`s carry the lookup key from the `*_started` line to the `*_completed` line;
     - or a `LINK_RESOURCE_IDENTITY` catalog row / document row naming the subject.

     A catalog row is rejected when the record itself shows another *known* customer's identifiers. When those identifiers match nobody, the row is kept but flagged as a conflict.
   - **strong:** a deletion-worker event that is unique to one request's reporting slot and also present in that request's audit-time evidence.
   - **weak:** other workflow inferences:
     - exclusivity propagation;
     - learned run cadence (consecutive actions of one run are 390 s or 449 s apart);
     - clean-run filter;
     - evidence-coverage consistency for account ties.

     The deletion worker emits its events in each request's reporting slot, and the primary-account result mirrors `reported_status`. These are used only as linkage clues, never as evidence of state.
   - **unresolved:** genuine ties. They are recorded in diagnostics and, under the default `no-guess` policy, never written to `output.csv`.

   In the final run every deletion status depends only on direct links. Removing all workflow inference (`--link-policy corroborated`) changes 0 statuses.

5. **State at `audit_at`.**
   - The latest observation at or before the cutoff decides the state.
   - At one snapshot instant, any surviving replica copy is a violation (replication drift).
   - Absence by omission is accepted only from snapshot captures, never from query-style lookups. A capture may override an explicit "present" only when it was taken for this audit (within 30h).
   - Later evidence (for example an account recreated after the audit) never changes the answer.
   - **Cutoff interpretation.** A statement timestamped at or before `audit_at` inside a file exported after it may link records and inform state, but it is never cited. Statements timestamped after `audit_at` are always ignored.
     - This is the narrowest reading consistent with the published examples. Seven of the 32 public answers include a record whose attribution depends on pre-cutoff statements in two such late exports, directly or through a tie-break: `evidence_02` for case_21, 24, 25, 26, 29 and 30, and `evidence_06` for case_09.
     - The literal whole-file reading is available as `--strict-capture-cutoff`. It drops exact-case accuracy on the public sample from 0.875 to 0.656.
     - On the 518 eval cases, the strict reading changes 126 cases and 2 statuses.

6. **Policy.** Categories map to `deletion_rules.csv`:

   | Category | Treatment |
   |---|---|
   | User profile, search entry, cache entry, export, marketing profile, secondary identifier, support attachment | Delete |
   | Support message, email delivery log, account tombstone | Redact (keep the stable reference, remove direct identifiers) |
   | Analytics / telemetry | Anonymize |
   | Security audit log within retention, active legal hold | Retain and verify present |
   | Backup | Retain, but block restore |
   | Active connector | Disable the data flow |

7. **Plan.**
   - `INCOMPLETE`: findings that cite the latest evidence file captured at or before `audit_at`, then remediation, then verification of the final state of **every** relevant record (remediation and verification have an empty `evidence_id`).
   - `COMPLETE`: verification steps only, each citing the evidence that proves the state.
   - **Completion guard.** The schema has no `UNKNOWN` status. A case with no evidenced violation is still reported `INCOMPLETE` (with only the checks that must pass, and no invented finding) when any of these holds:
     - a directly or strongly linked record's state at `audit_at` is unknown;
     - a violation is visible only in a file captured after `audit_at`;
     - an unattributed tie that the request is part of contains a record that is not proven compliant.

     It changes no public or eval answer under any link policy. It does prevent the false `COMPLETE` in the `suite_guard` fixtures.
   - A finding cites a file only when that file's own statement shows the violation; a mere mention of the record is not enough.
   - Steps are sorted by phase → operation-table order → `system_id` → `resource_id`, then renumbered from 1.

   The grader's sort already places `DISABLE_DATA_FLOW` and `BLOCK_RESTORE` before any record change, so dependency order and the serialized order never conflict.

---

## Results (measured)

| Evaluation set | Status acc. | Exact case | Step P / R / F1 | Field acc. | Sequence acc. |
|---|---|---|---|---|---|
| Public sample (32), default `no-guess` | 1.000 | 0.875 | 1.000 / 0.979 / 0.990 | 0.958 | 0.875 |
| Public sample (32), `--link-policy full` | 1.000 | 0.875 | 0.995 / 0.979 / 0.987 | 0.968 | 0.875 |
| Public sample, first-pass baseline | 1.000 | 0.844 | 0.990 / 0.974 / 0.982 | 0.967 | 0.844 |
| Public sample (32), `--strict-capture-cutoff` (comparison only) | 1.000 | 0.656 | 1.000 / 0.928 / 0.962 | 0.860 | 0.656 |
| Custom suites (14 hand-labelled synthetic cases) | 1.000 | 1.000 | 1.000 / 1.000 / 1.000 | 1.000 | 1.000 |

Full 518-case output:
- passes the independent validator and is byte-identical across runs;
- 153 `COMPLETE`, 355 `INCOMPLETE`, 10 `NOT_APPLICABLE`;
- 3,127 steps, of which 6.9% rest on weak (heuristic) links and none on unresolved ties.

Hidden-answer accuracy is **unknown**: no hidden labels were used or available. Details, ablations and the defect log are in [`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md).

## Optional LLM fallback

`python code/main.py --llm` consults Claude (`claude-opus-5-5` through the official `anthropic` SDK, with server-side refusal fallbacks) only for requests whose intent the rule classifier marks as low-confidence. The prompt is in `code/ghost_audit/prompts.md`, and the request text is treated as untrusted data. Without credentials the run continues deterministically.

In the final run every request was classified confidently, so no call was made. See [`code/evaluation/usage_report.md`](./code/evaluation/usage_report.md).

## Limitations

- **Missing references.** Three public reference records (`account_004`, `audit_record_6645`, `audit_record_5569`) appear nowhere in participant data, so they cannot be recovered.
- **Genuine ties.** 97 account events and 24 analytics events in the eval set cannot be attributed: same slot, same result, no identifiers. Seven more are unassignable.
  - Under the default, these are not asserted, and each affected case lacks one verification step.
  - `--link-policy full` pairs them deterministically, which is right about 33–50% of the time per tie.
- **OCR.** Screenshot evidence relies on OCR. With the pinned versions the OCR text was checked against the catalog rows and by visual inspection, and a clean install reproduces it exactly. Other OCR versions were not verified.
- **case_63.** The data catalog links `marketing_001` to the requester, but the screenshot shows an unknown person's identifiers. The uncontradicted catalog link is kept and flagged; this needs manual review.

## Challenge links

- Problem statement: [`problem_statement.md`](./problem_statement.md)
- Submission: https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists
