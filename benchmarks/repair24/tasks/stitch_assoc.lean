import Std

namespace Repair24

def stitch {α : Type} : List α → List α → List α
  | [], ys => ys
  | x :: xs, ys => x :: stitch xs ys

theorem stitch_assoc (xs ys zs : List Nat) : stitch (stitch xs ys) zs = stitch xs (stitch ys zs) :=
  -- PROOF_START
  by
  exact List.append_assoc xs ys zs
  -- PROOF_END

end Repair24
