by
  let _embedded := include_str "tracer-security-test-only"
  intro h
  exact ⟨h.2, h.1⟩
