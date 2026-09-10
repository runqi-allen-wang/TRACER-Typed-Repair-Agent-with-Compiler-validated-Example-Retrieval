by
  run_tac do
    let _ ← IO.getEnv "TRACER_SECURITY_TEST_ONLY"
    pure ()
  trivial
