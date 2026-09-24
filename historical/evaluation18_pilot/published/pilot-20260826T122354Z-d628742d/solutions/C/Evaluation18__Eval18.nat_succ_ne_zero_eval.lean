import Std

namespace Eval18


theorem nat_succ_ne_zero_eval (n : Nat) : Nat.succ n ≠ 0 :=
  -- PROOF_START
  by exact Nat.succ_ne_zero n
  -- PROOF_END

end Eval18
