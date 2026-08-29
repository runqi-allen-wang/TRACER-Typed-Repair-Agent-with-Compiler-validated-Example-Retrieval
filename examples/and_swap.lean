-- tags: propositional_logic and
example (p q : Prop) : p ∧ q → p ∨ q := by
  intro h
  exact Or.inl h.left
