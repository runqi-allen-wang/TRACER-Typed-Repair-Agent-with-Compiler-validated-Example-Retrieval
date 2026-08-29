import Std

theorem complex_local_context
    {α : Type} [Coe α Nat]
    (x : α) (h : (x : Nat) = 0) :
    (x : Nat) = 0 := by
  exact x

