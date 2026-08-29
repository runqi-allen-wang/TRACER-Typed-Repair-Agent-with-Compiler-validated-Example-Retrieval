-- tags: natural_numbers rewriting relations
example (n : Nat) : n ≤ Nat.succ n := by exact Nat.le_succ n
example (n m : Nat) : m + Nat.succ n = Nat.succ (m + n) := by exact Nat.add_succ m n
example (n : Nat) : n ≤ Nat.succ n := by exact Nat.le_succ n
