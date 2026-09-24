import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_add (a b : Nat) : double (a + b) = double a + double b :=
  -- PROOF_START
  by
  induction b with
  | zero => simp [double]
  | succ n ih =>
    rw [Nat.add_succ, double.eq_2, ih, double.eq_2, Nat.add_assoc]
  -- PROOF_END

end Repair24
