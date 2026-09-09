import Std

class Printable (α : Type) where
  print : α → String

def renderWithoutInstance {α : Type} (x : α) : String :=
  Printable.print x
