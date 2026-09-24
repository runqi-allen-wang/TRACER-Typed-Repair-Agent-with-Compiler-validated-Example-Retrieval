import Std

namespace Repair24




theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    rcases h with ⟨x, hx⟩
    cases hx with
    | inl hP => exact Or.inl ⟨x, hP⟩
    | inr hQ => exact Or.inr ⟨x, hQ⟩
  · intro h
    cases h with
    | inl hP =>
        rcases hP with ⟨x, hPx⟩
        exact ⟨x, Or.inl hPx⟩
    | inr hQ =>
        rcases hQ with ⟨x, hQx⟩
        exact ⟨x, Or.inr hQx⟩
  -- PROOF_END

end Repair24
