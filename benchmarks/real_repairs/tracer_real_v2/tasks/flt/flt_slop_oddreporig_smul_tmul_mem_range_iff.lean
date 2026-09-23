/-
Copyright (c) 2026 Zachary Feng, Y. Samanda Zhang. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Zachary Feng, Y. Samanda Zhang
-/
module

public import FLT.Slop.RepresentationTheory.OddAbsIrredSlop

/-!
# Compatibility aliases for the original odd-representation namespace

The maintained proof of the odd-representation irreducibility criterion now lives in
`FLT.Slop.RepresentationTheory.OddAbsIrredSlop`, under `Slop.OddRep`.  This file keeps the old
`Slop.OddRepOrig` names available without recompiling a duplicate copy of the same proofs.
-/

@[expose] public section

open scoped TensorProduct

open Module

namespace Slop
namespace OddRepOrig

variable {k : Type*} [Field k]
variable {G : Type*} [Monoid G]
variable {V : Type*} [AddCommGroup V] [Module k V]

/-- Compatibility alias for `Slop.OddRep.baseChange`. -/
noncomputable abbrev baseChange (l : Type*) [Field l] [Algebra k l]
    (ρ : Representation k G V) : Representation l G (l ⊗[k] V) :=
  _root_.Slop.OddRep.baseChange l ρ

/-- Compatibility alias for `Slop.OddRep.adjoinRange`. -/
abbrev adjoinRange (ρ : Representation k G V) : Subalgebra k (Module.End k V) :=
  _root_.Slop.OddRep.adjoinRange ρ

/-- Compatibility alias for `Slop.OddRep.IsAbsolutelyIrreducible`. -/
abbrev IsAbsolutelyIrreducible (ρ : Representation k G V) : Prop :=
  _root_.Slop.OddRep.IsAbsolutelyIrreducible ρ

lemma isIrreducible_iff_forall (ρ : Representation k G V) :
    ρ.IsIrreducible ↔
      Nontrivial V ∧
        ∀ W : Submodule k V, (∀ g : G, ∀ v ∈ W, ρ g v ∈ W) → W = ⊥ ∨ W = ⊤ :=
  _root_.Slop.OddRep.isIrreducible_iff_forall ρ

lemma smul_tmul_mem_range_iff (l : Type*) [Field l] [Algebra k l]
    {e : V} (he : e ≠ 0) (c : l) :
    c ⊗ₜ[k] e ∈ LinearMap.range (TensorProduct.mk k l V 1) ↔
      ∃ a : k, algebraMap k l a = c :=
  -- PROOF_START
  by
  constructor
  · -- Forward: if `c ⊗ₜ e = 1 ⊗ₜ w`, apply `id ⊗ φ` for a functional `φ` with `φ e = 1`.
    rintro ⟨w, hw⟩
    -- `hw : 1 ⊗ₜ w = c ⊗ₜ e`
    obtain ⟨φ, hφ⟩ := Module.Projective.exists_dual_eq_one k he
    -- `ψ : l ⊗[k] V → l`, `x ⊗ₜ v ↦ φ v • x`.
    set ψ : l ⊗[k] V →ₗ[k] l :=
      (TensorProduct.rid k l).toLinearMap ∘ₗ LinearMap.lTensor l φ with hψ
    refine ⟨φ w, ?_⟩
    have key := congrArg ψ hw
    simp only [hψ, LinearMap.coe_comp, Function.comp_apply, TensorProduct.mk_apply,
      LinearMap.lTensor_tmul, LinearEquiv.coe_coe, TensorProduct.rid_tmul] at key
    -- `key : φ w • (1 : l) = φ e • c`
    rw [hφ, one_smul] at key
    rw [Algebra.algebraMap_eq_smul_one]
    exact key
  · -- Reverse: `algebraMap k l a ⊗ₜ e = 1 ⊗ₜ (a • e)`.
    rintro ⟨a, rfl⟩
    refine ⟨a • e, ?_⟩
    rw [TensorProduct.mk_apply, TensorProduct.tmul_smul, TensorProduct.smul_tmul',
      Algebra.algebraMap_eq_smul_one]

/-! ## Lemma 1.4 : `End_G(V) = k` -/

/-- **Lemma 1.4.** If `ρ` is irreducible and some `g : G` has a one-dimensional
fixed subspace (the eigenspace of `ρ g` for the eigenvalue `1`), then every
`G`-equivariant endomorphism of `V` is scalar. -/
  -- PROOF_END

lemma exists_smul_eq_of_commute
    (ρ : Representation k G V)
    (hirr : ρ.IsIrreducible)
    {g : G} (hg : finrank k (Module.End.eigenspace (ρ g) 1) = 1)
    (T : Module.End k V) (hT : ∀ h : G, Commute (ρ h) T) :
    ∃ μ : k, T = μ • (1 : Module.End k V) :=
  _root_.Slop.OddRep.exists_smul_eq_of_commute ρ hirr hg T hT

lemma adjoinRange_eq_top (ρ : Representation k G V) [FiniteDimensional k V]
    (hirr : ρ.IsIrreducible)
    (hEnd : ∀ T : Module.End k V, (∀ h : G, Commute (ρ h) T) →
      ∃ μ : k, T = μ • (1 : Module.End k V)) :
    adjoinRange ρ = ⊤ :=
  _root_.Slop.OddRep.adjoinRange_eq_top ρ hirr hEnd

lemma adjoinRange_baseChange_eq_top (ρ : Representation k G V) [FiniteDimensional k V]
    (l : Type*) [Field l] [Algebra k l]
    (h : adjoinRange ρ = ⊤) :
    adjoinRange (baseChange l ρ) = ⊤ :=
  _root_.Slop.OddRep.adjoinRange_baseChange_eq_top ρ l h

lemma isIrreducible_of_adjoinRange_eq_top (ρ : Representation k G V) [Nontrivial V]
    (h : adjoinRange ρ = ⊤) :
    ρ.IsIrreducible :=
  _root_.Slop.OddRep.isIrreducible_of_adjoinRange_eq_top ρ h

lemma isIrreducible_of_baseChange (ρ : Representation k G V)
    (l : Type*) [Field l] [Algebra k l]
    (h : (baseChange l ρ).IsIrreducible) :
    ρ.IsIrreducible :=
  _root_.Slop.OddRep.isIrreducible_of_baseChange ρ l h

theorem isIrreducible_baseChange_of_finrank_eigenspace_eq_one
    (ρ : Representation k G V) [FiniteDimensional k V]
    (l : Type*) [Field l] [Algebra k l]
    (hirr : ρ.IsIrreducible)
    {g : G} (hg : finrank k (Module.End.eigenspace (ρ g) 1) = 1) :
    (baseChange l ρ).IsIrreducible :=
  _root_.Slop.OddRep.isIrreducible_baseChange_of_finrank_eigenspace_eq_one ρ l hirr hg

theorem isIrreducible_iff_isAbsolutelyIrreducible
    (ρ : Representation k G V) [FiniteDimensional k V]
    {g : G} (hg : finrank k (Module.End.eigenspace (ρ g) 1) = 1) :
    ρ.IsIrreducible ↔ IsAbsolutelyIrreducible ρ :=
  _root_.Slop.OddRep.isIrreducible_iff_isAbsolutelyIrreducible_slop ρ hg

end OddRepOrig
end Slop
