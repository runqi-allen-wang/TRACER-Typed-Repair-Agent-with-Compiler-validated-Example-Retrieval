import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2

theorem double_value (n : Nat) : double n = n + n :=
  -- PROOF_START
  by
  exact double_eq_add n
  -- PROOF_END

end Repair24
