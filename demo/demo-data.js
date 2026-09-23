window.TRACER_DEMO = {
  evidence: {
    release: "research-six-arm-313f437f",
    tasks: 864,
    firstPass: 735,
    withinThree: 811,
    recovered: 76,
    firstRate: 85.1,
    withinThreeRate: 93.9,
    deltaPoints: 8.8
  },
  caseStudy: {
    model: "DeepSeek Flash v4.1",
    arm: "R-E · diagnostic-adaptive retrieval",
    problem: "Repair24.scale_add",
    repeat: 1,
    theorem: `def scale (a : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => scale a n + a

theorem scale_add (a m n : Nat) :
    scale a (m + n) = scale a m + scale a n := by
  induction n with
  | zero => simp [scale]
  | succ n ih => simp only [Nat.add_succ, scale]`,
    rounds: [
      {
        status: "failed",
        label: "Round 1",
        candidate: `by
  induction n with
  | zero => simp [scale]
  | succ n ih =>
      simp only [scale]
      rw [ih, Nat.add_assoc]`,
        diagnostic: `Tactic \`rewrite\` failed: Did not find an occurrence of
  scale a (m + n)
in the target expression
  scale a (m.add n) + a = scale a m + (scale a n + a)`,
        feedback: `category: compile_error
goal: scale a (m.add n) + a = scale a m + (scale a n + a)
actionable signal: expose the syntactic form expected by the induction hypothesis`,
        retrieval: "natural_numbers.lean · score 0.3760",
        compileMs: 1010.4
      },
      {
        status: "passed",
        label: "Round 2",
        candidate: `by
  induction n with
  | zero => simp [scale]
  | succ n ih =>
      change scale a (m + n) + a =
        scale a m + (scale a n + a)
      rw [ih, Nat.add_assoc]`,
        diagnostic: "Lean compiled the candidate successfully.",
        feedback: "The new `change` step aligns the goal with the induction hypothesis before rewriting.",
        retrieval: "natural_numbers.lean · score 0.5199",
        compileMs: 1031.9
      }
    ]
  }
};
