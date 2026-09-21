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
      have h : scale a (Nat.add m n) = scale a m + scale a n := ih
      simp only [scale]
      rw [h]
      exact Nat.add_assoc _ _ _
  -- PROOF_END

end Repair24
