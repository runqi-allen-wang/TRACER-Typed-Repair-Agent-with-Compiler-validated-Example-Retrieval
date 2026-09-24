import Std

namespace Eval18


theorem or_swap_eval (p q : Prop) : p ∨ q → q ∨ p :=
  -- PROOF_START
  fun h : p ∨ q => Or.elim h (fun hp : p => Or.inr hp) (fun hq : q => Or.inl hq)
  -- PROOF_END

end Eval18
