import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_add (a b : Nat) : double (a + b) = double a + double b :=
  -- PROOF_START
  by
  induction b with
  | zero => rfl
  | succ b ih =>
      calc
        double (a + Nat.succ b) = double (a + b) + 2 := rfl
        _ = (double a + double b) + 2 := by rw [ih]
        _ = double a + (double b + 2) := by rw [Nat.add_assoc]
        _ = double a + double (Nat.succ b) := rfl
  -- PROOF_END

end Repair24
