import Std

namespace Repair24




theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    rcases h with ⟨x, hx⟩
    cases hx with
    | inl hp => exact Or.inl ⟨x, hp⟩
    | inr hq => exact Or.inr ⟨x, hq⟩
  · intro h
    cases h with
    | inl hP =>
        rcases hP with ⟨x, hp⟩
        exact ⟨x, Or.inl hp⟩
    | inr hQ =>
        rcases hQ with ⟨x, hq⟩
        exact ⟨x, Or.inr hq⟩
  -- PROOF_END

end Repair24
