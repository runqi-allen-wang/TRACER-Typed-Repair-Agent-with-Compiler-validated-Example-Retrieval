import Std

namespace Repair24




theorem forall_and (P Q : Nat → Prop) : (∀ x, P x ∧ Q x) ↔ (∀ x, P x) ∧ (∀ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    constructor
    · intro x
      exact (h x).1
    · intro x
      exact (h x).2
  · intro h x
    exact ⟨h.1 x, h.2 x⟩
  -- PROOF_END

end Repair24
