import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2

theorem double_add (a b : Nat) : double (a + b) = double a + double b :=
  -- PROOF_START
  by
  rfl
  -- PROOF_END

end Repair24
