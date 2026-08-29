import Std

namespace Eval18


theorem bool_cases_eval (b : Bool) : b = true ∨ b = false :=
  -- PROOF_START
  by cases b <;> simp
  -- PROOF_END

end Eval18
