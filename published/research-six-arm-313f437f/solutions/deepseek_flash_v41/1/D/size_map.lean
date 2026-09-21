import Std

namespace Repair24

def transform {α β : Type} (f : α → β) : List α → List β
  | [] => []
  | x :: xs => f x :: transform f xs

def size {α : Type} : List α → Nat
  | [] => 0
  | _ :: xs => size xs + 1


theorem size_map (f : Nat → Nat) (xs : List Nat) : size (transform f xs) = size xs :=
  -- PROOF_START
  by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
    exact congrArg Nat.succ ih
  -- PROOF_END

end Repair24
