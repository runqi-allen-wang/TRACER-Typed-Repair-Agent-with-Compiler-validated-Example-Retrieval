import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_even (n : Nat) : ∃ k, double n = k + k :=
  -- PROOF_START
  by
  have h : double n = n + n := by
    induction n with
    | zero => rfl
    | succ n ih =>
        calc
          double (n + 1) = double n + 2 := rfl
          _ = (n + n) + 2 := by rw [ih]
          _ = (n + 1) + (n + 1) := by ac_rfl
  exact ⟨n, h⟩
  -- PROOF_END

end Repair24
