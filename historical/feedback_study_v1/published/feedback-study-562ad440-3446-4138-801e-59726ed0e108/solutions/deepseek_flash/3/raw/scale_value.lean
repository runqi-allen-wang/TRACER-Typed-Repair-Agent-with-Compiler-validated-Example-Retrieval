import Std

namespace Repair24

def scale (a : Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => scale a n + a


theorem scale_value (a n : Nat) : scale a n = a * n :=
  -- PROOF_START
  Nat.rec (motive := fun n => scale a n = a * n)
  rfl
  (fun n ih => congrArg (fun x => x + a) ih)
  n
  -- PROOF_END

end Repair24
