import Std

namespace Repair24

def double : Nat → Nat
  | 0 => 0
  | n + 1 => double n + 2


theorem double_even (n : Nat) : ∃ k, double n = k + k :=
  -- PROOF_START
  by
  refine ⟨n, ?_⟩
  induction n with
  | zero => rfl
  | succ n ih =>
      simp [double, ih, Nat.add_assoc, Nat.add_comm, Nat.add_left_comm]
  -- PROOF_END

end Repair24
