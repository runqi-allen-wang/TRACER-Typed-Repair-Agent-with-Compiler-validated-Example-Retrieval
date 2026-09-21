import Std

namespace Repair24




theorem surjective_comp (f g : Nat → Nat) (hf : ∀ y, ∃ x, f x = y) (hg : ∀ y, ∃ x, g x = y) : ∀ y, ∃ x, g (f x) = y :=
  -- PROOF_START
  by
  intro y
  cases hg y with
  | intro z hz =>
    cases hf z with
    | intro x hx =>
      exact ⟨x, hx.symm ▸ hz⟩
  -- PROOF_END

end Repair24
