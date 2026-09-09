import Std

example (p q : Prop) (hp : p) : p ∧ q := by
  constructor
  · exact hp
