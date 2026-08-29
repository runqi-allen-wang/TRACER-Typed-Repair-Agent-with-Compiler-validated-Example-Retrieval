import Std

namespace Eval18


theorem or_assoc_eval (p q r : Prop) : p ∨ (q ∨ r) → (p ∨ q) ∨ r :=
  -- PROOF_START
  fun h =>
  Or.elim h
    (fun hp => Or.inl (Or.inl hp))
    (fun hqr =>
      Or.elim hqr
        (fun hq => Or.inl (Or.inr hq))
        (fun hr => Or.inr hr))
  -- PROOF_END

end Eval18
