import Std

namespace Repair24

def scale (a : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => scale a n + a


theorem scale_value (a n : Nat) : scale a n = a * n :=
  -- PROOF_START
  by
  induction n with
  | zero => rfl
  | succ n ih =>
      change scale a n + a = a * (n + 1)
      rw [ih, Nat.mul_succ]
  -- PROOF_END

end Repair24
