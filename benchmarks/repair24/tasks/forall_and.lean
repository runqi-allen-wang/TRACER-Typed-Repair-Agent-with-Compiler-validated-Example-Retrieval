import Std

namespace Repair24



theorem forall_and (P Q : Nat → Prop) : (∀ x, P x ∧ Q x) ↔ (∀ x, P x) ∧ (∀ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h; exact h
  · intro h; exact h
  -- PROOF_END

end Repair24
