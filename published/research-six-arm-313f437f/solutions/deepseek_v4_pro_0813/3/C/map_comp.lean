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
      calc
        transform g (transform f (x :: xs))
            = g (f x) :: transform g (transform f xs) := rfl
        _ = g (f x) :: transform (fun y => g (f y)) xs := by
          rw [ih]
        _ = transform (fun y => g (f y)) (x :: xs) := rfl
  -- PROOF_END

end Repair24
