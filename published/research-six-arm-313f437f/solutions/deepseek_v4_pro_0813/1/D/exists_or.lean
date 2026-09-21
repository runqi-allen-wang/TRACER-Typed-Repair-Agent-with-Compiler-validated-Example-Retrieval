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
    rcases h with hleft | hright
    · rcases hleft with ⟨x, hp⟩
      exact ⟨x, Or.inl hp⟩
    · rcases hright with ⟨x, hq⟩
      exact ⟨x, Or.inr hq⟩
  -- PROOF_END

end Repair24
