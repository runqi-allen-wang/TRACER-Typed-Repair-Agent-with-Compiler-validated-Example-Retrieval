import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_add (a b : Nat) : double (a + b) = double a + double b :=
  -- PROOF_START
  by
  induction a with
  | zero => simp [double, Nat.zero_add]
  | succ a ih =>
      rw [Nat.succ_add]
      simp only [double, ih]
      ac_rfl
  -- PROOF_END

end Repair24
