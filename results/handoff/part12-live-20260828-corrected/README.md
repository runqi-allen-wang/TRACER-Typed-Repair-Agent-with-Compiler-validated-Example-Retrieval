# Part 1 + Part 2 paired experiment results

This directory contains the corrected reviewed handoff artifacts for the 25-problem
FATE-M Part 1 Experience / Part 2 CapsuleFeedback paired experiment run on
2026-08-28. It supersedes the earlier `part12-live-20260828` package, which is
retained as historical evidence.
The source artifacts were checked for credential-like values and local absolute
paths before export. No content replacements were required. Text line endings
were normalized to LF for portable Git checkouts, and the exported hashes are
recorded in `handoff.json`.

## Frozen conditions

- Source revision: `8fdeace98781a672a6a2eeaf4e398890e139f16a`.
- AxProverBase revision: `06dfadc9ab439755af5efcfe0add95bfef2733c7`
- Provider: AI4Math `yxai`
- Model: `gpt-5.6-sol` (`openai:gpt-5.6-sol` in Ax/LangChain configuration)
- Endpoint: `https://yxai.chat/v1`
- Wire API: Responses
- Reasoning effort: `high`
- Response storage: disabled
- Lean: 4.28.0
- Benchmark: FATE-M, 25 paired problems

## Results

| Metric | Part 1 Experience | Part 2 CapsuleFeedback |
| --- | ---: | ---: |
| Successful proofs | 25/25 | 25/25 |
| Total rounds | 39 | 36 |
| Compilation errors | 14 | 11 |
| LLM calls | 79 | 36 |
| Tokens | 656657 | 274742 |

The strict pairing check passed for all 25 problems. Both conditions used the
same first-round candidate for each problem. Part 2 recorded zero Memory calls,
zero Capsule-internal LLM calls, and zero Capsule-internal compiler calls.

## Files

- `baseline-full.jsonl`: Part 1 per-problem run records.
- `capsule-full.jsonl`: Part 2 per-problem run records.
- `part2-first-round-full.json`: shared first-round candidate cache.
- `capsule-metrics-full.jsonl`: Part 2 integration and call telemetry.
- `pairing-full.json`: strict pairing validation report.
- `handoff.json`: source revision, file sizes, and SHA-256 checksums.

The API credential and local dependency caches are not included.
