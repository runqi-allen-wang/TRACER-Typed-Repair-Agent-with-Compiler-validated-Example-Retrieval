import Std

theorem core_goal_standalone (p q : Prop) (hp : p) (hq : q) : p ∧ q := by exact ⟨hp, hq⟩
