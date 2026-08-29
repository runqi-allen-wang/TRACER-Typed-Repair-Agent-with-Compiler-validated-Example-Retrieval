import Std

namespace Eval18


theorem and_assoc_eval (p q r : Prop) : (p ∧ q) ∧ r → p ∧ (q ∧ r) :=
  -- PROOF_START
  fun h => ⟨h.left.left, ⟨h.left.right, h.right⟩⟩
  -- PROOF_END

end Eval18
