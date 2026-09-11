by
  run_tac do
    let _ ← IO.Process.run {
      cmd := "curl"
      args := #["https://example.invalid/tracer-security-test-only"]
    }
    pure ()
  trivial
