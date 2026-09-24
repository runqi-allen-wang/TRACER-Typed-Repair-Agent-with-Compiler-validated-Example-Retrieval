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
    · rcases hP with ⟨x, hP⟩
      exact ⟨x, Or.inl hP⟩
    · rcases hQ with ⟨x, hQ⟩
      exact ⟨x, Or.inr hQ⟩
  -- PROOF_END

end Repair24
