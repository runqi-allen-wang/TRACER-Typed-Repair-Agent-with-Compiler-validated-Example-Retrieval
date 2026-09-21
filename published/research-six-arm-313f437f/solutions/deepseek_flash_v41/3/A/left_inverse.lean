import Std

namespace Repair24




theorem left_inverse (f g : Nat → Nat) (h : ∀ x, g (f x) = x) : ∀ a b, f a = f b → a = b :=
  -- PROOF_START
  fun a b hab => Eq.trans (Eq.symm (h a)) (Eq.trans (congrArg g hab) (h b))
  -- PROOF_END

end Repair24
