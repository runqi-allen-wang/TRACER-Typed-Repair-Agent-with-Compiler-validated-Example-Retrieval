import Std

namespace Eval18


theorem function_congruent_eval {α β : Type} (f : α → β) {a b : α} : a = b → f a = f b :=
  -- PROOF_START
  fun h => congrArg f h
  -- PROOF_END

end Eval18
