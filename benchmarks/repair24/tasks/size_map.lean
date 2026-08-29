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
  exact size_transform f xs
  -- PROOF_END

end Repair24
