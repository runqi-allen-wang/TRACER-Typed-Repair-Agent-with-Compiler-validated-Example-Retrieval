import Std

theorem corePair {p q : Prop} (hp : p) (hq : q) : p ∧ q := ⟨hp, hq⟩

theorem core_goal_same_file {p q : Prop} (hp : p) (hq : q) : p ∧ q := by exact corePair hp hq
