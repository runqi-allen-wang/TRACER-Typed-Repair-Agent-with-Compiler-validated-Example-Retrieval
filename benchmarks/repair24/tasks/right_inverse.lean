import Std

namespace Repair24



theorem right_inverse (f g : Nat → Nat) (h : ∀ y, f (g y) = y) : ∀ y, ∃ x, f x = y :=
  -- PROOF_START
  by
  intro y; exact ⟨y, h y⟩
  -- PROOF_END

end Repair24
