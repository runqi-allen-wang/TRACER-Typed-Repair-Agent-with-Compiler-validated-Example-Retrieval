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
      change n + 1 ≤ tri n + (n + 1)
      exact Nat.le_trans (Nat.le_add_left (n + 1) n) (Nat.add_le_add_right ih (n + 1))
  -- PROOF_END

end Repair24
