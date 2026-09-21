import Std

namespace Repair24




theorem surjective_comp (f g : Nat → Nat) (hf : ∀ y, ∃ x, f x = y) (hg : ∀ y, ∃ x, g x = y) : ∀ y, ∃ x, g (f x) = y :=
  -- PROOF_START
  by
  intro y
  rcases hg y with ⟨x0, hgx⟩
  rcases hf x0 with ⟨x1, hfx⟩
  exact ⟨x1, by rw [hfx, hgx]⟩
  -- PROOF_END

end Repair24
