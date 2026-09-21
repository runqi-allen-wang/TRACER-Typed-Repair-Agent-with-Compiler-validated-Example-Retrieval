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
  | succ b ih => simp [double, ih, Nat.add_assoc, Nat.add_comm, Nat.add_left_comm]
  -- PROOF_END

end Repair24
