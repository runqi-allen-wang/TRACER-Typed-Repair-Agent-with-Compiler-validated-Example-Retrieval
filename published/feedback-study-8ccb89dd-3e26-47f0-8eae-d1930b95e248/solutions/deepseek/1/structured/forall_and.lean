import Std

namespace Repair24




theorem forall_and (P Q : Nat → Prop) : (∀ x, P x ∧ Q x) ↔ (∀ x, P x) ∧ (∀ x, Q x) :=
  -- PROOF_START
  Iff.intro (fun h => And.intro (fun x => And.left (h x)) (fun x => And.right (h x))) (fun h x => And.intro (And.left h x) (And.right h x))
  -- PROOF_END

end Repair24
