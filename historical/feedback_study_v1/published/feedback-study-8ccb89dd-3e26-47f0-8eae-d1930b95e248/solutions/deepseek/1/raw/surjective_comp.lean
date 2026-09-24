import Std

namespace Repair24




theorem surjective_comp (f g : Nat → Nat) (hf : ∀ y, ∃ x, f x = y) (hg : ∀ y, ∃ x, g x = y) : ∀ y, ∃ x, g (f x) = y :=
  -- PROOF_START
  by
  intro y
  rcases hg y with ⟨x0, hx0⟩
  rcases hf x0 with ⟨x1, hx1⟩
  exact ⟨x1, by rw [hx1, hx0]⟩
  -- PROOF_END

end Repair24
