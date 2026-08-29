import Std

namespace LeanCapsuleChallenge

def normalizeNat (n : Nat) : Nat := n + 1

theorem same_file_dependency : normalizeNat 1 = 2 := by
  rfl

end LeanCapsuleChallenge

