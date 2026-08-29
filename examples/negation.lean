-- tags: propositional_logic negation
example (p : Prop) : p ∧ True → p := by
  intro h
  exact h.left
