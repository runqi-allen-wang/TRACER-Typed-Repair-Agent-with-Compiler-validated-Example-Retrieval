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
      calc
        scale a (m + (n+1)) = scale a ((m+n)+1) := by rw [Nat.add_succ]
        _ = scale a (m+n) + a := by rw [scale]
        _ = (scale a m + scale a n) + a := by rw [ih]
        _ = scale a m + (scale a n + a) := by rw [Nat.add_assoc]
        _ = scale a m + scale a (n+1) := by rw [← scale]
  -- PROOF_END

end Repair24
