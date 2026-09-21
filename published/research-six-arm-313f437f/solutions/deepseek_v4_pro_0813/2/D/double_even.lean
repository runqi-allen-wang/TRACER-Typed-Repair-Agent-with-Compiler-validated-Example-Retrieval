import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_even (n : Nat) : ∃ k, double n = k + k :=
  -- PROOF_START
  by
  induction n with
  | zero => exact ⟨0, rfl⟩
  | succ n ih =>
      rcases ih with ⟨k, hk⟩
      exact ⟨k + 1, by
        calc
          double (n + 1) = double n + 2 := rfl
          _ = k + k + 2 := by rw [hk]
          _ = (k + 1) + (k + 1) := by
            rw [Nat.succ_add]
            rfl⟩
  -- PROOF_END

end Repair24
