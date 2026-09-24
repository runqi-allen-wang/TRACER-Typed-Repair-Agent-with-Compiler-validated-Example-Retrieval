import Std

namespace Eval18


theorem nat_succ_ne_zero_eval (n : Nat) : Nat.succ n ≠ 0 :=
  -- PROOF_START
  fun h => Nat.noConfusion h
  -- PROOF_END

end Eval18
