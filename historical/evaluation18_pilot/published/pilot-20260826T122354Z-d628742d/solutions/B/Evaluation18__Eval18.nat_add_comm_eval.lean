import Std

namespace Eval18


theorem nat_add_comm_eval (n m : Nat) : n + m = m + n :=
  -- PROOF_START
  Nat.add_comm n m
  -- PROOF_END

end Eval18
