import Std

namespace Repair24



theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h; rcases h with ⟨x, hx⟩; exact Or.inl ⟨x, hx⟩
  · intro h; exact h
  -- PROOF_END

end Repair24
