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
  | succ n ih =>
      calc
        double (n + 1) = double n + 2 := rfl
        _ = (n + n) + 2 := by rw [ih]
        _ = (n + 1) + (n + 1) := by omega
  -- PROOF_END

end Repair24
