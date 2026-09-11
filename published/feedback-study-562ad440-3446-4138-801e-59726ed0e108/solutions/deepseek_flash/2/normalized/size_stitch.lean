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
  | cons x xs ih =>
      simp only [stitch, size]
      rw [ih]
      exact (Nat.add_assoc (size xs) (size ys) 1).trans
        ((congrArg (fun t => size xs + t) (Nat.add_comm (size ys) 1)).trans
          (Nat.add_assoc (size xs) 1 (size ys)).symm)
  -- PROOF_END

end Repair24
