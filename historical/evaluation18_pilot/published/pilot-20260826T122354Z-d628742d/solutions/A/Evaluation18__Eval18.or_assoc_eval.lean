import Std

namespace Eval18


theorem or_assoc_eval (p q r : Prop) : p ∨ (q ∨ r) → (p ∨ q) ∨ r :=
  -- PROOF_START
  fun h : p ∨ (q ∨ r) =>
  Or.elim h
    (fun hp : p => Or.inl (Or.inl hp))
    (fun hqr : q ∨ r =>
      Or.elim hqr
        (fun hq : q => Or.inl (Or.inr hq))
        (fun hr : r => Or.inr hr))
  -- PROOF_END

end Eval18
