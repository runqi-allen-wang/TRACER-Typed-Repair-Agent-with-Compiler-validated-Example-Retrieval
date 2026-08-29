import CoreGoal.Helper

open CoreGoalProject

theorem core_goal_project_local {p q : Prop} (hp : p) (hq : q) : p ∧ q := by exact projectPair hp hq
