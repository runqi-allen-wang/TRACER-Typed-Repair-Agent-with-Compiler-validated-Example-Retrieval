import Std

namespace Repair24

def omap {α β : Type} (f : α → β) : Option α → Option β
  | none => none
  | some x => some (f x)

def obind {α β : Type} : Option α → (α → Option β) → Option β
  | none, _ => none
  | some x, f => f x

theorem omap_bind (x : Option Nat) (f : Nat → Option Nat) (g : Nat → Nat) : omap g (obind x f) = obind x (fun n => omap g (f n)) :=
  -- PROOF_START
  by
  exact omap_obind x f g
  -- PROOF_END

end Repair24
