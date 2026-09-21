import Std

namespace Repair24

def stitch {α : Type} : List α → List α → List α
  | [], ys => ys
  | x :: xs, ys => x :: stitch xs ys

def transform {α β : Type} (f : α → β) : List α → List β
  | [] => []
  | x :: xs => f x :: transform f xs


theorem map_stitch (f : Nat → Nat) (xs ys : List Nat) : transform f (stitch xs ys) = stitch (transform f xs) (transform f ys) :=
  -- PROOF_START
  by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      simp only [stitch, transform]
      exact congrArg (fun t => f x :: t) ih
  -- PROOF_END

end Repair24
