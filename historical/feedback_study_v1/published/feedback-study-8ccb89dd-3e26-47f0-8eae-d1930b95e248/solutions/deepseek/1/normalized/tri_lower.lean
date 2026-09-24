import Std

namespace Repair24

def tri : Nat → Nat
  | 0 => 0
  | n + 1 => tri n + (n + 1)


theorem tri_lower (n : Nat) : n ≤ tri n :=
  -- PROOF_START
  by
  induction n with
  | zero => simp [tri]
  | succ n ih =>
      exact Nat.succ_le_succ (Nat.le_trans ih (Nat.le_add_right (tri n) n))
  -- PROOF_END

end Repair24
