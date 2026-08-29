import Std

namespace Repair24

def omap {α β : Type} (f : α → β) : Option α → Option β
  | none => none
  | some x => some (f x)

theorem omap_comp (f g : Nat → Nat) (x : Option Nat) : omap g (omap f x) = omap (fun n => g (f n)) x :=
  -- PROOF_START
  by
  rfl
  -- PROOF_END

end Repair24
