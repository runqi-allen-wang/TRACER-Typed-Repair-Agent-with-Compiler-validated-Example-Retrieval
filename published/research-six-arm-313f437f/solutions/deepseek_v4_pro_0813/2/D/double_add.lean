import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_add (a b : Nat) : double (a + b) = double a + double b :=
  -- PROOF_START
  by
  induction b with
  | zero => rfl
  | succ n ih =>
      simp [double]
      rw [ih]
      exact Nat.add_assoc (double a) (double n) 2
  -- PROOF_END

end Repair24
