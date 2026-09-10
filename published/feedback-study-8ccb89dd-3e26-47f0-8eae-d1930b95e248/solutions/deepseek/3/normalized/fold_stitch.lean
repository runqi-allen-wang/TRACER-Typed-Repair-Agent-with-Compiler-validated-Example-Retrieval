import Std

namespace Repair24

def stitch {α : Type} : List α → List α → List α
  | [], ys => ys
  | x :: xs, ys => x :: stitch xs ys

def fold {α β : Type} (f : β → α → β) : β → List α → β
  | z, [] => z
  | z, x :: xs => fold f (f z x) xs


theorem fold_stitch (f : Nat → Nat → Nat) (xs ys : List Nat) (z : Nat) : fold f z (stitch xs ys) = fold f (fold f z xs) ys :=
  -- PROOF_START
  by
  induction xs generalizing z with
  | nil => rfl
  | cons x xs ih =>
      change fold f (f z x) (stitch xs ys) = fold f (fold f (f z x) xs) ys
      exact ih (f z x)
  -- PROOF_END

end Repair24
