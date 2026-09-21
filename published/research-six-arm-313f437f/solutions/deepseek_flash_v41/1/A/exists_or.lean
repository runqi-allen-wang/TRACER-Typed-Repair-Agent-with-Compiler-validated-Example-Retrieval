import Std

namespace Repair24




theorem exists_or (P Q : Nat → Prop) : (∃ x, P x ∨ Q x) ↔ (∃ x, P x) ∨ (∃ x, Q x) :=
  -- PROOF_START
  ⟨fun h => Exists.elim h (fun x hx => Or.elim hx (fun hp => Or.inl ⟨x, hp⟩) (fun hq => Or.inr ⟨x, hq⟩)), fun h => Or.elim h (fun hP => Exists.elim hP (fun x hx => ⟨x, Or.inl hx⟩)) (fun hQ => Exists.elim hQ (fun x hx => ⟨x, Or.inr hx⟩))⟩
  -- PROOF_END

end Repair24
