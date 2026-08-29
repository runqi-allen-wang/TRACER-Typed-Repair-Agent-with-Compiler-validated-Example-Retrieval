import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2

theorem double_even (n : Nat) : ∃ k, double n = k + k :=
  -- PROOF_START
  by
  exact ⟨n, rfl⟩
  -- PROOF_END

end Repair24
