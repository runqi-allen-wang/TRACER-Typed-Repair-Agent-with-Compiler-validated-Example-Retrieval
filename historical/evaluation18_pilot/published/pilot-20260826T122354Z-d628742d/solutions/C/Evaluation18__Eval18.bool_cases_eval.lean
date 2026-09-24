import Std

namespace Eval18


theorem bool_cases_eval (b : Bool) : b = true ∨ b = false :=
  -- PROOF_START
  Bool.rec (Or.inr rfl) (Or.inl rfl) b
  -- PROOF_END

end Eval18
