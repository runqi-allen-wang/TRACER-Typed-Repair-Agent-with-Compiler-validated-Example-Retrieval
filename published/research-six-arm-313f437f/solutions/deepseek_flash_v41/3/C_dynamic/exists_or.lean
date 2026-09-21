import Std

namespace Repair24




theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  by
  constructor
  · intro h
    rcases h with ⟨x, hx⟩
    rcases hx with hpx | hqx
    · exact Or.inl ⟨x, hpx⟩
    · exact Or.inr ⟨x, hqx⟩
  · intro h
    rcases h with hpx | hqx
    · rcases hpx with ⟨x, hpx⟩
      exact ⟨x, Or.inl hpx⟩
    · rcases hqx with ⟨x, hqx⟩
      exact ⟨x, Or.inr hqx⟩
  -- PROOF_END

end Repair24
