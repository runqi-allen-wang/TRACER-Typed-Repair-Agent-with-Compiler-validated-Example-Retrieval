import Std

namespace Repair24




theorem left_inverse (f g : Nat → Nat) (h : ∀ x, g (f x) = x) : ∀ a b, f a = f b → a = b :=
  -- PROOF_START
  by
  intro a b hab
  calc
    a = g (f a) := (h a).symm
    _ = g (f b) := congrArg g hab
    _ = b := h b
  -- PROOF_END

end Repair24
