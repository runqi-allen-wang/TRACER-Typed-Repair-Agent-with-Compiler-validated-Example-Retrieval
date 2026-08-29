import Std

namespace Eval18


theorem nat_lt_succ_self_eval (n : Nat) : n < Nat.succ n :=
  -- PROOF_START
  Nat.lt_succ_self n
  -- PROOF_END

end Eval18
