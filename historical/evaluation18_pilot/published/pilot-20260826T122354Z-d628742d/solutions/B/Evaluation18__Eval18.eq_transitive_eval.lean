import Std

namespace Eval18


theorem eq_transitive_eval {α : Type} {a b c : α} : a = b → b = c → a = c :=
  -- PROOF_START
  fun hab hbc => hab.trans hbc
  -- PROOF_END

end Eval18
