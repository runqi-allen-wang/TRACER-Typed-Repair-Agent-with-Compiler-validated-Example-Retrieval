import Std

def coreAcceptNat (n : Nat) : Nat := n

theorem core_type_same_file : coreAcceptNat true = 1 := by
  rfl
