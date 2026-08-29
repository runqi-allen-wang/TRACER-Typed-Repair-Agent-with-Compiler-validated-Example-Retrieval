import Std

namespace Repair24

def transform {α β : Type} (f : α → β) : List α → List β
  | [] => []
  | x :: xs => f x :: transform f xs

theorem map_comp (f g : Nat → Nat) (xs : List Nat) : transform g (transform f xs) = transform (fun x => g (f x)) xs :=
  -- PROOF_START
  by
  rfl
  -- PROOF_END

end Repair24
