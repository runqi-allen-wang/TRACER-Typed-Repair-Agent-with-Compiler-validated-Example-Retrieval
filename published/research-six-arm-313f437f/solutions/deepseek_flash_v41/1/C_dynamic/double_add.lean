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
  | succ m ih =>
      rw [Nat.add_succ]
      simp only [double]
      rw [ih]
      rw [Nat.add_assoc]
  -- PROOF_END

end Repair24
