import Std

namespace Repair24




theorem exists_and (P : Nat → Prop) (Q : Prop) : (∃ x, P x ∧ Q) ↔ (∃ x, P x) ∧ Q :=
  -- PROOF_START
  by
  constructor
  · rintro ⟨x, hp, hq⟩
    exact ⟨⟨x, hp⟩, hq⟩
  · intro h
    rcases h with ⟨hx, hq⟩
    rcases hx with ⟨x, hp⟩
    exact ⟨x, hp, hq⟩
  -- PROOF_END

end Repair24
