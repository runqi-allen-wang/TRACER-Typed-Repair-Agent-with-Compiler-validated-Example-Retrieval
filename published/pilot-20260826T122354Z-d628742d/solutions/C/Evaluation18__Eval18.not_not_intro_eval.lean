import Std

namespace Eval18


theorem not_not_intro_eval (p : Prop) : p → ¬¬p :=
  -- PROOF_START
  fun hp hnp => hnp hp
  -- PROOF_END

end Eval18
