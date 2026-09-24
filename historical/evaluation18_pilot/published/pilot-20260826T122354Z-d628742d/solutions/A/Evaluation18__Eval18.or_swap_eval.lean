import Std

namespace Eval18


theorem or_swap_eval (p q : Prop) : p ∨ q → q ∨ p :=
  -- PROOF_START
  fun h => h.elim (fun hp => Or.inr hp) (fun hq => Or.inl hq)
  -- PROOF_END

end Eval18
