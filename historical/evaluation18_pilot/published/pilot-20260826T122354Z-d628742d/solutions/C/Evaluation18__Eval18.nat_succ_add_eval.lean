import Std

namespace Eval18


theorem nat_succ_add_eval (n m : Nat) : Nat.succ n + m = Nat.succ (n + m) :=
  -- PROOF_START
  by exact Nat.succ_add n m
  -- PROOF_END

end Eval18
