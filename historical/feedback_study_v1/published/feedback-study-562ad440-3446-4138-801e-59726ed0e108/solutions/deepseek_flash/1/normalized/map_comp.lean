import Std

namespace Repair24

def transform {α β : Type} (f : α → β) : List α → List β
  | [] => []
  | x :: xs => f x :: transform f xs


theorem map_comp (f g : Nat → Nat) (xs : List Nat) : transform g (transform f xs) = transform (fun x => g (f x)) xs :=
  -- PROOF_START
  by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      change g (f x) :: transform g (transform f xs) =
             g (f x) :: transform (fun x => g (f x)) xs
      exact congrArg (List.cons (g (f x))) ih
  -- PROOF_END

end Repair24
