import Std

namespace Repair24




theorem injective_comp (f g : Nat → Nat) (hf : ∀ a b, f a = f b → a = b) (hg : ∀ a b, g a = g b → a = b) : ∀ a b, g (f a) = g (f b) → a = b :=
  -- PROOF_START
  by
  intro a b h
  exact hf a b (hg (f a) (f b) h)
  -- PROOF_END

end Repair24
