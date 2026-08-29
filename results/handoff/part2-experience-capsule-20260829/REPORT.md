# B arm handoff: Experience + CapsuleFeedback

This directory contains the exported raw artifacts for the independent B arm of
the FATE-M Part 2 study. The arm combines AxProverBase `ExperienceProcessor`
with deterministic `CapsuleFeedback` so that the feedback-format effect can be
separated from the Memory change in the original Part 1/Part 2 comparison.

## Frozen conditions

- Benchmark: FATE-M, 25 paired problems.
- B condition: `capsule_experience`.
- Memory: `ExperienceProcessor`.
- Feedback: `CapsuleFeedback` (`feedback_mode=capsule`).
- AxProverBase commit: `06dfadc9ab439755af5efcfe0add95bfef2733c7`.
- Model: `gpt-5.6-sol` (`openai:gpt-5.6-sol` in the Ax configuration).
- Provider endpoint: `https://yxai.chat/v1`.
- Wire API: Responses; response storage disabled; reasoning effort `high`.
- Candidate policy: `tracer-candidate-v2`, with meta-execution and unsafe
  declarations blocked.
- Maximum iterations: 4; maximum input budget: 65,536 tokens.
- Source export revision: `1e1f1ade384324638ebf88a2c96ec14842b716fd`.

The B run reused the complete Part 1 first-round proposal (`code`,
`reasoning`, `imports`, and `opens`) for every task. The canonical Part 1
baseline used for pairing is
`../part12-live-20260828-corrected/baseline-full.jsonl`.

## Results

| Metric | B `capsule_experience` |
| --- | ---: |
| Tasks | 25 |
| Final successes | 20/25 (80.0%) |
| Total rounds | 47 |
| LLM requests | 69 |
| Proposer / reviewer / Memory requests | 22 / 20 / 27 |
| Lean compilation calls | 47 |
| Compilation errors | 27 |
| Compilation timeouts | 0 |
| Reached the four-round limit | 5 |
| Total tokens | 659,791 |
| API/infrastructure errors | 0 |

Sixteen tasks succeeded with the shared first-round candidate. Of the nine
shared first-round failures, B repaired four (`fate04`, `fate17`, `fate18`,
and `fate24`), for a descriptive repair rate of 4/9 (44.4%). The remaining
five tasks reached the four-round limit.

## Integrity checks

- `pairing.json` reports `ok=true` and 25 paired tasks.
- The first-round `code`, `reasoning`, `imports`, and `opens` match the Part 1
  baseline for all 25 tasks.
- All 25 result rows are unique and marked
  `condition=capsule_experience`, `memory_mode=experience_capsule_feedback`,
  and `memory_processor=ExperienceProcessor`.
- The 77 telemetry records contain 25 shared-candidate events, 25 run summaries,
  and 27 feedback events. Reported Memory calls agree with
  `calls.memory_calls`.
- The included state snapshots are the final per-session CapsuleFeedback state
  used by the run; they are provided for audit and are not dependency caches.
- No API credential or local dependency cache is included.

Run the following offline checks from the repository root; neither command
calls a model API:

```text
python scripts/validate_b_handoff.py
python scripts/validate_part2_pairing.py \
  --baseline results/handoff/part12-live-20260828-corrected/baseline-full.jsonl \
  --capsule results/handoff/part2-experience-capsule-20260829/capsule-experience.jsonl \
  --capsule-condition capsule_experience
```

## Interpretation boundary

This is one model, one batch, and one descriptive B run. It does not establish
statistical significance, a general proof-repair advantage, or a causal result
for the full ABCD design. The B run and the Raw/Capsule Part 3 run were made in
separate batches and must remain separately reported until a common preregistered
four-arm batch is run.

The `openai:` prefix in the Ax model field is a model namespace. The actual
recorded endpoint for this run is the AI4Math `yxai` endpoint above; exporting
these artifacts does not change provider configuration or authentication.
