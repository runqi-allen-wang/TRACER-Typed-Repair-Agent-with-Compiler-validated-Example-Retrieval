-- tags: equality functions
example {α : Type} {a b c : α} : a = b → b = c → c = a := by
  intro hab hbc
  exact (Eq.trans hab hbc).symm

example {α β : Type} (f : α → β) {a b : α} : a = b → f b = f a := by
  intro hab
  cases hab
  rfl
