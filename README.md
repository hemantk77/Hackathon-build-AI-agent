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
python -m pip install -r code/requirements.txt   # only pypdf is required for a normal run
python code/main.py                               # writes ./output.csv (518 rows)
python code/validate_output.py                    # independent contract validator
python code/evaluation/main.py                    # score the 32 public samples
python code/evaluation/main.py --custom           # score the custom adversarial suite
python -m unittest discover -s code/tests         # unit tests
```

Requirements:

- Python 3.10 or newer.
- No network access and no API keys for the default run.
- A full run takes about 2 seconds.

Useful flags:

| Command | Purpose |
|---|---|
| `python code/main.py --requests sample_deletion_requests.csv --out sample_predictions.csv` | Audit another request file in `dataset/` |
| `python code/main.py --diagnostics diag.json` | Per-case resources, link basis, policy treatment, state and citation |
| `python code/main.py --data-dir <dir>` | Run against another dataset with the same layout (used by the custom suite) |
| `python code/evaluation/main.py --verbose` | Per-case missing/extra steps against the reference answers |
| `python code/evaluation/custom_cases/build_custom_cases.py` | Rebuild the custom adversarial fixtures |
| `python code/package_submission.py` | Build `code.zip` (excludes `dataset/`, caches, secrets, nested archives) |

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
    llm.py, prompts.md       optional Claude fallback (off by default)
  tests/test_components.py   15 unit tests
  evaluation/
    main.py                  scorer (status, exact-case, step P/R/F1, field, sequence, LCS)
    custom_cases/            5 hand-labelled adversarial cases (+ builder script)
    evaluation_report.md     metrics, custom cases, failures and fixes
    usage_report.md          model and token usage of the final run
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

4. **Resource discovery** (`linker.py`), strongest basis first:
   - **evidence:** an observation carrying one of the subject's identifiers, with observation time in `[requested_at, audit_at]`. Log `trace_id`s carry the lookup key from the `*_started` line to the `*_completed` line.
   - **catalog / document:** `LINK_RESOURCE_IDENTITY` rows, plus PDFs/screenshots captured within a day of the catalog row that display its reference. A screenshot row needs a direct identifier on that row to link a record.
   - **workflow:** deletion-worker events are emitted in each request's reporting slot. Primary-account submissions occur about 1h before `reported_at`, and their result mirrors `reported_status` (SUCCESS↔COMPLETE, PARTIAL↔PARTIALLY_COMPLETE, FAILED↔NOT_STARTED). Successful policy actions land about 0.5h before and follow-ups 0.5–2h after. Events are assigned by global constraint elimination across all 550 requests: one resource per system per request, and never a resource already tied to another subject.
   - **alignment:** remaining ties are narrowed by record order inside snapshot bundles. The bundles list every collection in a consistent subject order, which was verified on every bundle.
   - **tie_guess:** a still-tied primary account (each request has exactly one), or a perfect matching of indistinguishable events, is paired deterministically and flagged in diagnostics.

5. **State at `audit_at`.**
   - The latest observation at or before the cutoff decides the state.
   - At one snapshot instant, any surviving replica copy is a violation (replication drift).
   - The audit-time capture of the account store overrides an older contradicting observation.
   - Later evidence (for example an account recreated after the audit) never changes the answer.

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
   - Steps are sorted by phase → operation-table order → `system_id` → `resource_id`, then renumbered from 1.

   The grader's sort already places `DISABLE_DATA_FLOW` and `BLOCK_RESTORE` before any record change, so dependency order and the serialized order never conflict.

---

## Results (measured)

| Evaluation set | Status acc. | Exact case | Step P / R / F1 | Field acc. | Sequence acc. |
|---|---|---|---|---|---|
| Public sample (32 cases) | 1.000 | 0.844 | 0.990 / 0.974 / 0.982 | 0.967 | 0.844 |
| Custom adversarial suite (5 cases) | 1.000 | 1.000 | 1.000 / 1.000 / 1.000 | 1.000 | 1.000 |

The full 518-case output passes the independent validator. It is byte-identical across runs and splits into 153 `COMPLETE`, 355 `INCOMPLETE` and 10 `NOT_APPLICABLE`.

Hidden-answer accuracy is **unknown**: no hidden labels were used or available. Details, ablations and the defect log are in [`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md).

## Optional LLM fallback

`python code/main.py --llm` consults Claude (`claude-opus-5-5` through the official `anthropic` SDK, with server-side refusal fallbacks) only for requests whose intent the rule classifier marks as low-confidence. The prompt is in `code/ghost_audit/prompts.md`, and the request text is treated as untrusted data. Without credentials the run continues deterministically.

In the final run every request was classified confidently, so no call was made. See [`code/evaluation/usage_report.md`](./code/evaluation/usage_report.md).

## Limitations

- About 3% of reference resources in the public sample appear nowhere in participant data, for example two security audit records and one hand-crafted account. They cannot be recovered.
- Some workflow events cannot be told apart from evidence: same slot, same result, no identifiers. Account ties (105) and perfect-matching analytics ties (36) are resolved by a deterministic guess, which is right about half the time on true ties. They are flagged as `tie_guess` in `--diagnostics`.
- Screenshot evidence relies on OCR. The text cache for the supplied images is shipped and was checked against the catalog rows and by visual inspection.
- `marketing_001` (case_63) is linked by the data catalog to the requester, but the screenshot shows another person's name. The catalog link was followed; this is a judgment call that needs manual review.

## Challenge links

- Problem statement: [`problem_statement.md`](./problem_statement.md)
- Submission: https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists
