import Std

namespace Repair24




theorem not_exists (P : Nat → Prop) : (¬ ∃ x, P x) ↔ ∀ x, ¬ P x :=
  -- PROOF_START
  Iff.intro
  (fun h x hx => h ⟨x, hx⟩)
  (fun h hx => hx.elim (fun x hx => h x hx))
  -- PROOF_END

end Repair24
