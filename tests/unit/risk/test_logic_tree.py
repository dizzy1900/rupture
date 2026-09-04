"""The GSIM logic tree: weights honoured exactly, and the tree it is not saying so (ADR-0037)."""

from __future__ import annotations

import numpy as np
import pytest

from rupture.adapters.groundmotion import NativeGsimEngine, registry
from rupture.adapters.groundmotion import logic_trees as lt
from rupture.domain.groundmotion import GsimBranch, GsimLogicTree, Site
from rupture.domain.hazard import ScenarioRupture
from rupture.domain.money import ModelProvenance
from rupture.ports.ground_motion import LogicTreeGroundMotionEngine
from tests.unit.risk.conftest import site

SITES: tuple[Site, ...] = (site("near", 85.0, 28.05), site("far", 85.6, 28.4))


def test_every_branch_of_every_shipped_tree_is_a_verified_gsim() -> None:
    """A branch naming a model rupture has not verified would be a claim it cannot back."""
    verified = set(registry.names())
    for tree in lt.TREES.values():
        for branch in tree.branches:
            assert branch.gsim in verified, f"{tree.id}: {branch.gsim} is not in the registry"


def test_the_shipped_tree_names_what_it_leaves_out() -> None:
    tree = lt.ACTIVE_SHALLOW_CRUST_Q
    assert tree.provenance is ModelProvenance.ASSUMED
    assert set(tree.excluded) == set(lt.NOT_VERIFIED)
    assert tree.notes is not None
    assert "LOWER BOUND" in tree.notes


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to"):
        GsimLogicTree(
            id="bad",
            branches=(
                GsimBranch(id="a", gsim="BooreEtAl2014", weight=0.4, rationale="x"),
                GsimBranch(id="b", gsim="BooreEtAl2014LowQ", weight=0.4, rationale="x"),
            ),
        )


def test_a_tree_claiming_published_weights_must_cite_them() -> None:
    with pytest.raises(ValueError, match="cite where"):
        GsimLogicTree(
            id="unsourced",
            branches=(GsimBranch(id="a", gsim="BooreEtAl2014", weight=1.0, rationale="x"),),
            provenance=ModelProvenance.PUBLISHED,
        )


@pytest.mark.parametrize("n", [3, 7, 100, 999, 1000])
def test_allocation_is_exact_and_never_drops_a_branch(n: int) -> None:
    counts = lt.ACTIVE_SHALLOW_CRUST_Q.allocation(n)
    assert sum(counts) == n
    assert all(c >= 1 for c in counts)
    for count, branch in zip(counts, lt.ACTIVE_SHALLOW_CRUST_Q.branches, strict=True):
        assert abs(count / n - branch.weight) <= 2.0 / n


def test_allocation_refuses_fewer_realisations_than_branches() -> None:
    with pytest.raises(ValueError, match="cannot represent"):
        lt.ACTIVE_SHALLOW_CRUST_Q.allocation(2)


def test_the_native_engine_mixes_branches_and_the_field_says_so(
    crustal_rupture: ScenarioRupture,
) -> None:
    engine = NativeGsimEngine()
    assert isinstance(engine, LogicTreeGroundMotionEngine)
    field = engine.scenario_logic_tree(
        crustal_rupture,
        SITES,
        tree=lt.ACTIVE_SHALLOW_CRUST_Q,
        n_realisations=300,
        seed=42,
    )
    assert field.n_realisations == 300
    assert field.gsim == f"logic-tree:{lt.ACTIVE_SHALLOW_CRUST_Q.id}"
    assert field.notes is not None
    assert "MIXED FIELD" in field.notes
    for branch in lt.ACTIVE_SHALLOW_CRUST_Q.branches:
        assert branch.gsim in field.notes
    assert np.all(field.array() > 0.0)


def test_the_mixed_field_is_wider_than_any_single_branch_at_distance(
    crustal_rupture: ScenarioRupture,
) -> None:
    """The point of a tree: the model choice widens the spread, not just the aleatory term."""
    engine = NativeGsimEngine()
    far = (site("far", 86.5, 28.6),)
    medians = []
    for branch in lt.ACTIVE_SHALLOW_CRUST_Q.branches:
        field = engine.scenario(
            crustal_rupture, far, gsim=branch.gsim, n_realisations=1, truncation_level=0.0
        )
        medians.append(float(field.array()[0, 0]))
    assert max(medians) > min(medians) * 1.05


def test_the_tree_renders_as_an_openquake_gsim_logic_tree() -> None:
    xml = lt.gsim_logic_tree_nrml(lt.ACTIVE_SHALLOW_CRUST_Q)
    assert 'uncertaintyType="gmpeModel"' in xml
    assert 'applyToTectonicRegionType="Active Shallow Crust"' in xml
    for branch in lt.ACTIVE_SHALLOW_CRUST_Q.branches:
        assert f"<uncertaintyModel>{branch.gsim}</uncertaintyModel>" in xml
    assert xml.count("<logicTreeBranch ") == len(lt.ACTIVE_SHALLOW_CRUST_Q.branches)


def test_an_unknown_tree_is_refused_by_name() -> None:
    with pytest.raises(lt.GsimLogicTreeError, match="rupture ships"):
        lt.build("no-such-tree")
