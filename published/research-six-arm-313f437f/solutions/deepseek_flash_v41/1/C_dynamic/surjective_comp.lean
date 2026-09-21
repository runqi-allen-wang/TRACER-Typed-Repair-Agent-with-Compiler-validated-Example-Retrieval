import Std

namespace Repair24




theorem surjective_comp (f g : Nat → Nat) (hf : ∀ y, ∃ x, f x = y) (hg : ∀ y, ∃ x, g x = y) : ∀ y, ∃ x, g (f x) = y :=
  -- PROOF_START
  fun y =>
  match hg y with
  | ⟨z, hz⟩ =>
    match hf z with
    | ⟨x, hx⟩ =>
      ⟨x, Eq.trans (congrArg g hx) hz⟩
  -- PROOF_END

end Repair24
