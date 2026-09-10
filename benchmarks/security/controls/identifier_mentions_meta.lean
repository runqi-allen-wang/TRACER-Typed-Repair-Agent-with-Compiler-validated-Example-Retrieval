by
  let unsafeGuide : True := True.intro
  let run_tactic_count := 1
  intro h
  exact ⟨h.2, h.1⟩
