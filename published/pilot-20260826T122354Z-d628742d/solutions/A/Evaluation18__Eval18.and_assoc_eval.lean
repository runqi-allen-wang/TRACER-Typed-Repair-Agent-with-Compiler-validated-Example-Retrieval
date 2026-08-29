import Std

namespace Eval18


theorem and_assoc_eval (p q r : Prop) : (p ∧ q) ∧ r → p ∧ (q ∧ r) :=
  -- PROOF_START
  fun h => ⟨h.1.1, ⟨h.1.2, h.2⟩⟩
  -- PROOF_END

end Eval18
