# Part 3 Minimal Raw/Capsule Pilot

This is a small paired pilot on the frozen 25-problem FATE-M set.
Raw and Capsule both use `MemorylessProcessor` and the same cached first-round Proposal.
The comparison changes only the feedback delivered after a failed build:
Raw passes Ax's original `BuildFailedFeedback`; Capsule passes deterministic `CapsuleFeedback`.

## Scope

- The shared first-round candidate is validated field by field (`code`, `reasoning`, `imports`, `opens`).
- First-round candidate generation is excluded from Raw/Capsule repair cost.
- Results are a single-model, single-batch pilot; they are not a significance test or a general capability claim.
- Fixed model: `openai:gpt-5.6-sol`; endpoint: `https://yxai.chat/v1`; Responses API; `store=false`; reasoning `high`.
- Fixed AxProverBase commit: `06dfadc9ab439755af5efcfe0add95bfef2733c7`; FATE-M/Lean environment is recorded by the runner contract.

## Pairing

- Pairing gate: **PASS**
- Paired tasks: 25 / 25
- First-round successes: 16
- First-round failures: 9

## Aggregate

| Metric | Raw | Capsule | Capsule - Raw |
|---|---:|---:|---:|
| Successful tasks | 22 | 19 | -3 |
| Second-round repairs after first failure | 4 | 2 | -2 |
| Final repairs after first failure | 6 | 3 | -3 |
| Total rounds | 43 | 47 | 4 |
| Compilation errors | 21 | 28 | 7 |
| Proposer calls | 19 | 22 | 3 |
| Reviewer calls | 22 | 19 | -3 |
| Total LLM calls | 41 | 41 | 0 |
| Total tokens | 400862 | 432548 | 31686 |
| Repeated diagnostics | 0 | 0 | 0 |
| API/infra errors | 0 | 0 | 0 |

## Per-Task Differences

| Task | First-round reference | Raw | Capsule | Raw rounds | Capsule rounds | Raw repair | Capsule repair |
|---|---|---|---|---:|---:|---|---|
| `fate01` | success | pass | pass | 1 | 1 | no | no |
| `fate02` | success | pass | pass | 1 | 1 | no | no |
| `fate03` | success | pass | pass | 1 | 1 | no | no |
| `fate04` | failure | pass | pass | 2 | 2 | yes | yes |
| `fate05` | success | pass | pass | 1 | 1 | no | no |
| `fate06` | success | pass | pass | 1 | 1 | no | no |
| `fate07` | success | pass | pass | 1 | 1 | no | no |
| `fate08` | success | pass | pass | 1 | 1 | no | no |
| `fate09` | success | pass | pass | 1 | 1 | no | no |
| `fate10` | failure | pass | fail | 3 | 4 | yes | no |
| `fate11` | success | pass | pass | 1 | 1 | no | no |
| `fate12` | success | pass | pass | 1 | 1 | no | no |
| `fate13` | success | pass | pass | 1 | 1 | no | no |
| `fate14` | success | pass | pass | 1 | 1 | no | no |
| `fate15` | success | pass | pass | 1 | 1 | no | no |
| `fate16` | failure | pass | fail | 2 | 4 | yes | no |
| `fate17` | failure | pass | pass | 2 | 2 | yes | yes |
| `fate18` | failure | pass | fail | 2 | 4 | yes | no |
| `fate19` | failure | fail | fail | 4 | 4 | no | no |
| `fate20` | success | pass | pass | 1 | 1 | no | no |
| `fate21` | success | pass | pass | 1 | 1 | no | no |
| `fate22` | success | pass | pass | 1 | 1 | no | no |
| `fate23` | failure | fail | fail | 4 | 4 | no | no |
| `fate24` | failure | pass | pass | 4 | 3 | yes | yes |
| `fate25` | failure | fail | fail | 4 | 4 | no | no |

## Interpretation

The informative subset is the nine tasks whose shared first-round candidate failed to compile.
Read the per-task table and `capsule_minus_raw` together: a positive repair difference means Capsule repaired more such tasks, while a negative round/token difference means less measured work.
Any pairing error or infrastructure error makes the package unsuitable for a formal conclusion.
