import Std

namespace Repair24

def omap {α β : Type} (f : α → β) : Option α → Option β
  | none => none
  | some x => some (f x)

theorem omap_identity (x : Option Nat) : omap (fun n => n) x = x :=
  -- PROOF_START
  by
  cases x with
  | none => rfl
  | some n => skip
  -- PROOF_END

end Repair24
