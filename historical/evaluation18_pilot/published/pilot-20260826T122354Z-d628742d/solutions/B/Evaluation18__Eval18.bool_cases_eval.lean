import Std

namespace Eval18


theorem bool_cases_eval (b : Bool) : b = true ∨ b = false :=
  -- PROOF_START
  match b with
| true => Or.inl rfl
| false => Or.inr rfl
  -- PROOF_END

end Eval18
