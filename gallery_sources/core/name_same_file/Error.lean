import Std

def coreDouble (n : Nat) : Nat := n + n

theorem core_name_same_file : coreDoubel 2 = 4 := by
  decide
