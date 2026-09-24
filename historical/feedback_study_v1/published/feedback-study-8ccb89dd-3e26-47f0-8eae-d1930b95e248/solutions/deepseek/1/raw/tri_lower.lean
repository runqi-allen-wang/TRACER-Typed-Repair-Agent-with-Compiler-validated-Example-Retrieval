import Std

namespace Repair24

def tri : Nat → Nat
  | 0 => 0
  | n + 1 => tri n + (n + 1)


theorem tri_lower (n : Nat) : n ≤ tri n :=
  -- PROOF_START
  by
  cases n with
  | zero => exact Nat.le_refl 0
  | succ n => exact Nat.le_add_left (Nat.succ n) (tri n)
  -- PROOF_END

end Repair24
