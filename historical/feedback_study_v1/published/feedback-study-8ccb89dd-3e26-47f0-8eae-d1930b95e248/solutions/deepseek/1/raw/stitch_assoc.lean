import Std

namespace Repair24

def stitch {α : Type} : List α → List α → List α
  | [], ys => ys
  | x :: xs, ys => x :: stitch xs ys


theorem stitch_assoc (xs ys zs : List Nat) : stitch (stitch xs ys) zs = stitch xs (stitch ys zs) :=
  -- PROOF_START
  by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      calc
        stitch (stitch (x :: xs) ys) zs = stitch (x :: stitch xs ys) zs := rfl
        _ = x :: stitch (stitch xs ys) zs := rfl
        _ = x :: stitch xs (stitch ys zs) := by rw [ih]
        _ = stitch (x :: xs) (stitch ys zs) := rfl
  -- PROOF_END

end Repair24
