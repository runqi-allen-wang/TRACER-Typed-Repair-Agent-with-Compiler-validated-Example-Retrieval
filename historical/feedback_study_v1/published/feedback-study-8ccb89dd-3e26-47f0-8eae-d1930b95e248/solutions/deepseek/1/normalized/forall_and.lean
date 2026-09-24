import Std

namespace Repair24




theorem forall_and (P Q : Nat → Prop) : (∀ x, P x ∧ Q x) ↔ (∀ x, P x) ∧ (∀ x, Q x) :=
  -- PROOF_START
  Iff.intro
  (fun h => ⟨fun x => (h x).1, fun x => (h x).2⟩)
  (fun h x => ⟨h.1 x, h.2 x⟩)
  -- PROOF_END

end Repair24
