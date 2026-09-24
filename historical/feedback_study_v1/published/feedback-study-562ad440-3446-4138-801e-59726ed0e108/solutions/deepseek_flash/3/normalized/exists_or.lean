import Std

namespace Repair24




theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    rcases h with ⟨x, hx⟩
    rcases hx with hP | hQ
    · exact Or.inl ⟨x, hP⟩
    · exact Or.inr ⟨x, hQ⟩
  · intro h
    rcases h with hP | hQ
    · rcases hP with ⟨x, hx⟩
      exact ⟨x, Or.inl hx⟩
    · rcases hQ with ⟨x, hx⟩
      exact ⟨x, Or.inr hx⟩
  -- PROOF_END

end Repair24
