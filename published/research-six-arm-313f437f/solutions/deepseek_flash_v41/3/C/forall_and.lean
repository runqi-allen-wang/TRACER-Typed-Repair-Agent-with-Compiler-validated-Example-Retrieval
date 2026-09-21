import Std

namespace Repair24




theorem forall_and (P Q : Nat → Prop) : (∀ x, P x ∧ Q x) ↔ (∀ x, P x) ∧ (∀ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    constructor
    · intro x
      exact (h x).left
    · intro x
      exact (h x).right
  · intro h
    intro x
    constructor
    · exact h.left x
    · exact h.right x
  -- PROOF_END

end Repair24
