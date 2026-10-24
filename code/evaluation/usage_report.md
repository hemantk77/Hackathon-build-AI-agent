# Usage Report — Final Full-Dataset Run

The final `output.csv` (518 cases, SHA-256 `dd65f880…`) was produced by the second-pass implementation with:

```bash
python code/main.py
```

- **Default settings:** link policy `no-guess`, bundle-order resolver off, no `--llm` flag.
- **Determinism:** the run is deterministic.
- **Telemetry:** the run's own record, written by `code/main.py` to `code/evaluation/last_run_usage.json`, shows `model_calls: 0` and `llm_enabled: false`.
- **Comparison runs:** the `full` and `corroborated` link-policy runs, the evaluation runs and the custom suites made no model calls either.

## Production inference usage (the run that produced `output.csv`)

| Model provider | Model | Model calls | Input tokens | Output tokens | Total tokens | Estimated cost |
|---|---|---|---|---|---|---|
| — (none called) | — | 0 | 0 | 0 | 0 | $0.00 |
| **Overall** | | **0** | **0** | **0** | **0** | **$0.00** |

| Per-request figure (518 requests) | Value |
|---|---|
| Average model calls per request | 0 |
| Average tokens per request | 0 |
| Estimated cost per request | $0.00 |

Why there are no model calls:

- Every request intent, identity link, evidence interpretation, policy decision and plan was produced by deterministic code.
- The optional Claude fallback is consulted only for requests whose intent the rule classifier marks as low-confidence. All 518 requests were classified confidently (508 deletion, 10 non-deletion, which matches the 10 `CLASSIFY_REQUEST` rows in `system_activity.csv`). So even with `--llm` enabled, no call would have been made on this dataset.

Non-LLM local processing:

- **OCR.** The 11 screenshots were OCR'd once with RapidOCR, an ONNX model running locally (not a language model, no API, no cost). The text is cached in `code/ghost_audit/evidence_cache/` and the final run read the cache.
- **PDFs.** Text from the 4 PDFs was extracted locally with `pypdf`.

## If the optional fallback is enabled

| Item | Value |
|---|---|
| Provider / model | Anthropic, `claude-opus-5-5` (official `anthropic` SDK, server-side refusal fallback `fallbacks="default"`) |
| Price used for estimates | $4.00 per 1M input tokens, $20.00 per 1M output tokens (Anthropic first-party list price) |
| Calls | One call per low-confidence request (0 on this dataset) |
| Telemetry | Every call's `usage.input_tokens` / `usage.output_tokens`, model, stop reason and request id are recorded in `last_run_usage.json`, and per-model totals are computed by `ghost_audit/llm.py::estimate_cost`. |

No token counts were measured for this mode because it never fired; none are reported.

## Development-session usage (separate from production)

The solution was built interactively with **Claude Code** (model `claude-opus-5-5`); see `log.txt` for the transcript summary. That is the coding assistant's own usage, not part of the production pipeline. Its per-token totals are not exposed inside the session, so no development token or cost figure is claimed here.
