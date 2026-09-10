by
  -- 文档说明可以提到 run_tac、IO.getEnv 或 unsafe，但不执行它们。
  intro h
  exact ⟨h.2, h.1⟩
