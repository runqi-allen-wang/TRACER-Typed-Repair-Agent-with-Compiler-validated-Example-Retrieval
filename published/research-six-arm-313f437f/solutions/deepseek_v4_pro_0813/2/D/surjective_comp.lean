import Std

namespace Repair24




theorem surjective_comp (f g : Nat → Nat) (hf : ∀ y, ∃ x, f x = y) (hg : ∀ y, ∃ x, g x = y) : ∀ y, ∃ x, g (f x) = y :=
  -- PROOF_START
  by
  intro y
  obtain ⟨z, hgz⟩ := hg y
  obtain ⟨x, hfx⟩ := hf z
  exact ⟨x, by rw [hfx, hgz]⟩
  -- PROOF_END

end Repair24
