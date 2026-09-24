import Std

namespace Repair24

def scale (a : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => scale a n + a


theorem scale_add (a m n : Nat) : scale a (m + n) = scale a m + scale a n :=
  -- PROOF_START
  by
  induction n with
  | zero => simp [scale]
  | succ n ih =>
      simp only [scale]
      change scale a (m + n) + a = scale a m + (scale a n + a)
      rw [ih]
      exact Nat.add_assoc (scale a m) (scale a n) a
  -- PROOF_END

end Repair24
