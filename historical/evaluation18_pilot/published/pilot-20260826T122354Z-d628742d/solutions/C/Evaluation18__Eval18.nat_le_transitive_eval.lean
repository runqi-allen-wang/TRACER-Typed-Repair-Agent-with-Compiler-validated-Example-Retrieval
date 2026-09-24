import Std

namespace Eval18


theorem nat_le_transitive_eval {a b c : Nat} : a ≤ b → b ≤ c → a ≤ c :=
  -- PROOF_START
  fun hab hbc => Nat.le_trans hab hbc
  -- PROOF_END

end Eval18
