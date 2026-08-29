import Std

namespace Repair24



theorem not_exists (P : Nat → Prop) : (¬ ∃ x, P x) ↔ ∀ x, ¬ P x :=
  -- PROOF_START
  by
  constructor
  · intro h x hx; exact h hx
  · intro h hx; exact h hx
  -- PROOF_END

end Repair24
