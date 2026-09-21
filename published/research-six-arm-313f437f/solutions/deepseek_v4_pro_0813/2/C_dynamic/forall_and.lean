import Std

namespace Repair24




theorem forall_and (P Q : Nat → Prop) : (∀ x, P x ∧ Q x) ↔ (∀ x, P x) ∧ (∀ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    exact And.intro (fun x => (h x).left) (fun x => (h x).right)
  · intro h
    exact fun x => And.intro (h.left x) (h.right x)
  -- PROOF_END

end Repair24
