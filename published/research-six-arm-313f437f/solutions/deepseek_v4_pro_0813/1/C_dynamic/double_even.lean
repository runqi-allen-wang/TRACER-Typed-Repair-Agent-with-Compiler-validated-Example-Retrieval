import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_even (n : Nat) : ∃ k, double n = k + k :=
  -- PROOF_START
  by
  have h : ∀ n, double n = n + n := by
    intro n
    induction n with
    | zero => rfl
    | succ n ih =>
        calc
          double (Nat.succ n) = double n + 2 := rfl
          _ = (n + n) + 2 := by rw [ih]
          _ = (Nat.succ n) + (Nat.succ n) := by
            change (n+n)+2 = (n+1)+(n+1)
            ac_rfl
  exact ⟨n, h n⟩
  -- PROOF_END

end Repair24
