import Std

namespace Eval18


theorem nat_le_transitive_eval {a b c : Nat} : a ≤ b → b ≤ c → a ≤ c :=
  -- PROOF_START
  fun h1 h2 => Nat.le_trans h1 h2
  -- PROOF_END

end Eval18
