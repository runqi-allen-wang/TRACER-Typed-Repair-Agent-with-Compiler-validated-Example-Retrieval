import Std

namespace Eval18


theorem and_swap_eval (p q : Prop) : p ∧ q → q ∧ p :=
  -- PROOF_START
  fun h => ⟨h.right, h.left⟩
  -- PROOF_END

end Eval18
