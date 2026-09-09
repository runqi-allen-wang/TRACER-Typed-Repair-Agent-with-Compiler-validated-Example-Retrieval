import Std

example (p : Prop) : p ∨ ¬p := by
  by_cases hp : p
  · exact Or.inl hp
