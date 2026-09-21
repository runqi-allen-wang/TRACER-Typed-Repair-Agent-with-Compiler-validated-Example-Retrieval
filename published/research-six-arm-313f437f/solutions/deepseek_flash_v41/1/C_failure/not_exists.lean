import Std

namespace Repair24




theorem not_exists (P : Nat → Prop) : (¬ ∃ x, P x) ↔ ∀ x, ¬ P x :=
  -- PROOF_START
  by
  constructor
  · intro h x hx
    exact h ⟨x, hx⟩
  · intro h hx
    cases hx with
    | intro x hp =>
      exact h x hp
  -- PROOF_END

end Repair24
