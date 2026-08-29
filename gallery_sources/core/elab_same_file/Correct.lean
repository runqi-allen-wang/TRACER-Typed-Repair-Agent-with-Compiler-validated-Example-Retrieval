import Std

class CoreMarked (alpha : Type) where mark : alpha → Nat
instance : CoreMarked Nat where mark n := n
def coreMark {alpha : Type} [CoreMarked alpha] (x : alpha) : Nat := CoreMarked.mark x

theorem core_elab_same_file : coreMark (1 : Nat) = 1 := by
  rfl
