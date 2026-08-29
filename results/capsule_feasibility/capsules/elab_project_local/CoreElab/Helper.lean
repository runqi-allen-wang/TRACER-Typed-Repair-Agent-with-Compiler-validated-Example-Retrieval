namespace CoreElabProject

class ProjectMarked (alpha : Type) where mark : alpha → Nat
instance : ProjectMarked Nat where mark n := n
def projectMark {alpha : Type} [ProjectMarked alpha] (x : alpha) : Nat := ProjectMarked.mark x

end CoreElabProject
