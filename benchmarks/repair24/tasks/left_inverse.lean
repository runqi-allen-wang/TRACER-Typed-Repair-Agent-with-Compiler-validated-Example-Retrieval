import Std

namespace Repair24



theorem left_inverse (f g : Nat → Nat) (h : ∀ x, g (f x) = x) : ∀ a b, f a = f b → a = b :=
  -- PROOF_START
  by
  intro a b hab; exact hab
  -- PROOF_END

end Repair24
