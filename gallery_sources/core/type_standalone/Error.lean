import Std

theorem core_type_standalone : (1 : Nat) = 1 := by
  exact (show true = true from rfl)
