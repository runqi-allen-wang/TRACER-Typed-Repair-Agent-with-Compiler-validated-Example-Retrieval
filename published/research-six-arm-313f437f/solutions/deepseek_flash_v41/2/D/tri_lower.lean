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
  | succ n ih =>
      exact Nat.le_trans (Nat.succ_le_succ ih)
        (Nat.add_le_add_left (Nat.succ_le_succ (Nat.zero_le n)) (tri n))
  -- PROOF_END

end Repair24
