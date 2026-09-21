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
      simp only [double, ih, Nat.add_succ, Nat.succ_add, Nat.add_zero]
  -- PROOF_END

end Repair24
