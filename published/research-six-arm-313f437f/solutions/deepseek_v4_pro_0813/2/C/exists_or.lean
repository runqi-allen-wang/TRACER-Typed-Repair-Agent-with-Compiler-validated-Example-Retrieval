import Std

namespace Repair24




theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    rcases h with ⟨x, hx⟩
    rcases hx with hp | hq
    · exact Or.inl ⟨x, hp⟩
    · exact Or.inr ⟨x, hq⟩
  · intro h
    rcases h with hp | hq
    · rcases hp with ⟨x, hx⟩
      exact ⟨x, Or.inl hx⟩
    · rcases hq with ⟨x, hx⟩
      exact ⟨x, Or.inr hx⟩
  -- PROOF_END

end Repair24
