import Std

namespace Repair24

def stitch {α : Type} : List α → List α → List α
  | [], ys => ys
  | x :: xs, ys => x :: stitch xs ys

def size {α : Type} : List α → Nat
  | [] => 0
  | _ :: xs => size xs + 1

theorem size_stitch (xs ys : List Nat) : size (stitch xs ys) = size xs + size ys :=
  -- PROOF_START
  by
  induction xs with
  | nil => simp [stitch, size]
  | cons x xs ih => simp only [stitch, size]
  -- PROOF_END

end Repair24
