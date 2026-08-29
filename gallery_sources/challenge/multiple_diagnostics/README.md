# multiple_diagnostics

The correct proof applies `assumption` to both goals created by `constructor`.
The error version changes that one tactic to `rfl`, so the same mutation is
propagated to both subgoals by `<;>`.  The case checks how multiple ordered Lean
diagnostics are represented by the current two-error/700-character summary and
its `diagnostic_key`.

