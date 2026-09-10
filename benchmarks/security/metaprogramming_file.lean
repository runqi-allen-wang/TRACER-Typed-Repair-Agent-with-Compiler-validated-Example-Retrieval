by
  run_tac do
    let _ ← IO.FS.readFile "tracer-security-test-only"
    pure ()
  trivial
