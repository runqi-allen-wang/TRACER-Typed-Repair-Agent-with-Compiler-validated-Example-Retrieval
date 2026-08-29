import Std

namespace Repair24

def obind {α β : Type} : Option α → (α → Option β) → Option β
  | none, _ => none
  | some x, f => f x

theorem obind_assoc (x : Option Nat) (f g : Nat → Option Nat) : obind (obind x f) g = obind x (fun n => obind (f n) g) :=
  -- PROOF_START
  by
  cases x with
  | none => rfl
  | some n => exact Eq.refl n
  -- PROOF_END

end Repair24
