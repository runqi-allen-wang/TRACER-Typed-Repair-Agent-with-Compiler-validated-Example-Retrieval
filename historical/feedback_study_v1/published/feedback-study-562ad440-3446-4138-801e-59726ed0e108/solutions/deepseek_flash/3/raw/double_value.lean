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
    change double n + 2 = (n + 1) + (n + 1)
    rw [ih]
    rw [show (2 : Nat) = 1 + 1 by rfl]
    ac_rfl
  -- PROOF_END

end Repair24
