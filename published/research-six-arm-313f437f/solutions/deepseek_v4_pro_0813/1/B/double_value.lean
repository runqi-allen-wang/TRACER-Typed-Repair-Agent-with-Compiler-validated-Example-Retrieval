import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_value (n : Nat) : double n = n + n :=
  -- PROOF_START
  by
  induction n with
  | zero => rfl
  | succ k ih =>
      calc
        double (k + 1) = double k + 2 := by rfl
        _ = (k + k) + 2 := by rw [ih]
        _ = (k + 1) + (k + 1) := by omega
  -- PROOF_END

end Repair24
