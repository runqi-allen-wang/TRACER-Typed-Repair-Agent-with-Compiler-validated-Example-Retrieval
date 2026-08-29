import Std

namespace Eval18


theorem or_swap_eval (p q : Prop) : p ∨ q → q ∨ p :=
  -- PROOF_START
  by
  intro h
  cases h with
  | inl hp => exact Or.inr hp
  | inr hq => exact Or.inl hq
  -- PROOF_END

end Eval18
