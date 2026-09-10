import Std

namespace Repair24




theorem surjective_comp (f g : Nat → Nat) (hf : ∀ y, ∃ x, f x = y) (hg : ∀ y, ∃ x, g x = y) : ∀ y, ∃ x, g (f x) = y :=
  -- PROOF_START
  by
  intro y
  obtain ⟨x, hx⟩ := hg y
  obtain ⟨a, ha⟩ := hf x
  exact ⟨a, by rw [ha]; exact hx⟩
  -- PROOF_END

end Repair24
