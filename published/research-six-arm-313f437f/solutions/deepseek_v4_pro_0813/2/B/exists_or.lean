import Std

namespace Repair24




theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · rintro ⟨x, hx⟩
    cases hx with
    | inl hP => exact Or.inl ⟨x, hP⟩
    | inr hQ => exact Or.inr ⟨x, hQ⟩
  · intro h
    cases h with
    | inl hP => rcases hP with ⟨x, hx⟩; exact ⟨x, Or.inl hx⟩
    | inr hQ => rcases hQ with ⟨x, hx⟩; exact ⟨x, Or.inr hx⟩
  -- PROOF_END

end Repair24
