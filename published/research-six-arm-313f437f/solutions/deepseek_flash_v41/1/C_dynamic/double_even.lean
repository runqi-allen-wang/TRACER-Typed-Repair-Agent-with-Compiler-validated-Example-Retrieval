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
      refine ⟨k + 1, ?_⟩
      change double n + 2 = (k + 1) + (k + 1)
      rw [hk]
      calc
        (k + k) + 2 = k + (k + 2) := Nat.add_assoc k k 2
        _ = k + ((k + 1) + 1) := rfl
        _ = k + (1 + (k + 1)) := by rw [Nat.add_comm (k + 1) 1]
        _ = (k + 1) + (k + 1) := (Nat.add_assoc k 1 (k + 1)).symm
  -- PROOF_END

end Repair24
