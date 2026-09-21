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
        scale a (m + Nat.succ n) = scale a (Nat.succ (m + n)) := by rw [Nat.add_succ]
        _ = scale a (m + n) + a := by simp [scale]
        _ = scale a m + scale a n + a := by rw [ih]
        _ = scale a m + (scale a n + a) := by rw [Nat.add_assoc]
        _ = scale a m + scale a (Nat.succ n) := by simp [scale]
  -- PROOF_END

end Repair24
