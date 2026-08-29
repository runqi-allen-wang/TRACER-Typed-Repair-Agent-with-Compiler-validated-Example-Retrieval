import Std

namespace Repair24



theorem exists_and (P : Nat → Prop) (Q : Prop) : (∃ x, P x ∧ Q) ↔ (∃ x, P x) ∧ Q :=
  -- PROOF_START
  by
  constructor
  · rintro ⟨x, hp, hq⟩; exact ⟨⟨x, hp⟩, hq⟩
  · intro h
  -- PROOF_END

end Repair24
