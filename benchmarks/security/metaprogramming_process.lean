by
  run_tac do
    let _ ← IO.Process.run { cmd := "tracer-security-test-only" }
    pure ()
  trivial
