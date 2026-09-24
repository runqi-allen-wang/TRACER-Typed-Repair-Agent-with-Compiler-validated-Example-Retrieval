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
    simp [double, ih, Nat.add_assoc, Nat.add_comm, Nat.add_left_comm]
  -- PROOF_END

end Repair24
