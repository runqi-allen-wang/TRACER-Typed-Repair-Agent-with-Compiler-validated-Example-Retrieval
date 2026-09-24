import Std

namespace Eval18


theorem nat_succ_add_eval (n m : Nat) : Nat.succ n + m = Nat.succ (n + m) :=
  -- PROOF_START
  by
  induction m with
  | zero => rfl
  | succ m ih => exact congrArg Nat.succ ih
  -- PROOF_END

end Eval18
