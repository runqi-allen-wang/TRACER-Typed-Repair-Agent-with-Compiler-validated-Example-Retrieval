import Std

namespace Repair24

def scale (a : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => scale a n + a


theorem scale_add (a m n : Nat) : scale a (m + n) = scale a m + scale a n :=
  -- PROOF_START
  by
  induction n with
  | zero => simp [scale, Nat.add_zero]
  | succ n ih =>
      simp [scale, Nat.add_succ, ih, Nat.add_assoc]
  -- PROOF_END

end Repair24
