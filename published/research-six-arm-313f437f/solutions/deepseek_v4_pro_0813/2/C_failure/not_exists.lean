import Std

namespace Repair24




theorem not_exists (P : Nat → Prop) : (¬ ∃ x, P x) ↔ ∀ x, ¬ P x :=
  -- PROOF_START
  by
  constructor
  · intro h x hx
    exact h ⟨x, hx⟩
  · intro h hx
    rcases hx with ⟨x, hpx⟩
    exact h x hpx
  -- PROOF_END

end Repair24
