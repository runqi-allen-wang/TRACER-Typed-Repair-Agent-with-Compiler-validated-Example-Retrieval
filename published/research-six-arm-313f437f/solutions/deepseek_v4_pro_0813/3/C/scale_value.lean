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
      calc
        scale a (n + 1) = scale a n + a := by rfl
        _ = a * n + a := by rw [ih]
        _ = a * (n + 1) := by rw [Nat.mul_succ]
  -- PROOF_END

end Repair24
