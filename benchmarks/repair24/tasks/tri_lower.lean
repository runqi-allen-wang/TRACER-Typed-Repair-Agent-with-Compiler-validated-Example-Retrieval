import Std

namespace Repair24

def tri : Nat → Nat
  | 0 => 0
  | n + 1 => tri n + (n + 1)

theorem tri_lower (n : Nat) : n ≤ tri n :=
  -- PROOF_START
  by
  induction n with
  | zero => exact Nat.le_refl 0
  | succ n ih => exact ih
  -- PROOF_END

end Repair24
