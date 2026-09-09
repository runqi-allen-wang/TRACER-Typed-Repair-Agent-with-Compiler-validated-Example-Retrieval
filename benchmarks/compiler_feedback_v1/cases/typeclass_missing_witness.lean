import Std

class Witness (α : Type) where
  witness : α

example : Nat := Witness.witness (α := Nat)
