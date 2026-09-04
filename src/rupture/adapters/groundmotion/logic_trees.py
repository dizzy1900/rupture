"""The GSIM logic trees rupture ships, and an honest account of what they are not (ADR-0037).

A loss interval computed from one GSIM is conditional on that GSIM. ``docs/RISK.md`` section 8
already shows how much model choice moves this corridor: swapping BSSA14 for the BC Hydro
interface model changes the MHT median PGA from 0.53 g to 0.78 g and the expected loss by 21 %.
A logic tree is how a hazard model carries that epistemic uncertainty instead of hiding it, and
this module is where rupture's live.

**What is here, stated plainly.** rupture ships one runnable tree for the Himalayan corridor's
tectonic class, and its three branches are the *same* NGA-West2 model under its three published
regional anelastic-attenuation adjustments: global, high-Q (China and Turkey) and low-Q (Italy
and Japan). Each branch is a separately verified GSIM — each reproduces OpenQuake's own committed
expected values within the tolerance recorded in ``docs/RISK.md``.

**What it is not.** It is not the multi-model tree a national or regional PSHA would use. Such a
tree for active shallow crust carries several *independent* NGA-West2 models (Chiou & Youngs
2014, Campbell & Bozorgnia 2014, Abrahamson, Silva & Kamai 2014, Idriss 2014) which differ far
more from one another than one model's Q-regions differ from each other. rupture has implemented
and verified none of those four, so shipping them as branch names would be a claim it cannot
back. They are named in :attr:`GsimLogicTree.excluded` on the tree itself, and the consequence is
recorded everywhere the tree is used: **the epistemic spread this tree produces is a lower bound
on GSIM epistemic uncertainty, not an estimate of it.**

The weights are ``assumed`` and the tree says so. No published weighting for the Q-region choice
in the Himalaya was found; the region's crustal attenuation is itself an open question, so the
three branches are given equal weight, which is the statement "rupture cannot choose between
them" rather than a claim about which is right.
"""

from __future__ import annotations

from rupture.domain.groundmotion import GsimBranch, GsimLogicTree
from rupture.domain.money import ModelProvenance

BSSA14_REFERENCE = (
    "Boore, D.M., Stewart, J.P., Seyhan, E. & Atkinson, G.M. (2014). NGA-West2 equations for "
    "PGA, PGV and 5 % damped PSA for shallow crustal earthquakes. Earthquake Spectra 30(3), "
    "1057-1085. doi:10.1193/070113EQS184M (title abbreviated; see docs/RISK.md). The regional "
    "anelastic-attenuation adjustments Dc3 for high-Q and low-Q regions are the paper's own."
)

NOT_VERIFIED: tuple[str, ...] = (
    "ChiouYoungs2014",
    "CampbellBozorgnia2014",
    "AbrahamsonEtAl2014",
    "Idriss2014",
)
"""Models a regional active-crustal tree would carry that rupture has not implemented or verified.

Naming them on the tree is the point: a reader can see exactly which epistemic alternatives the
reported interval does **not** contain.
"""

LOWER_BOUND_NOTE = (
    "the branches of this tree are three regional anelastic-attenuation variants of ONE "
    "NGA-West2 model, not independent models, so the spread across them is a LOWER BOUND on "
    "GSIM epistemic uncertainty rather than an estimate of it (ADR-0037)"
)

ACTIVE_SHALLOW_CRUST_Q = GsimLogicTree(
    id="rupture-asc-bssa14-q-v0",
    tectonic_region="Active Shallow Crust",
    branches=(
        GsimBranch(
            id="global-q",
            gsim="BooreEtAl2014",
            weight=1.0 / 3.0,
            rationale=(
                "the model's default global anelastic attenuation (Dc3 = 0), which is what a "
                "study with no regional constraint uses"
            ),
            source_refs=(BSSA14_REFERENCE,),
        ),
        GsimBranch(
            id="high-q",
            gsim="BooreEtAl2014HighQ",
            weight=1.0 / 3.0,
            rationale=(
                "the paper's high-Q adjustment, derived for China and Turkey: less anelastic "
                "loss with distance, so higher motion at the far end of the corridor"
            ),
            source_refs=(BSSA14_REFERENCE,),
        ),
        GsimBranch(
            id="low-q",
            gsim="BooreEtAl2014LowQ",
            weight=1.0 / 3.0,
            rationale=(
                "the paper's low-Q adjustment, derived for Italy and Japan: more anelastic loss "
                "with distance"
            ),
            source_refs=(BSSA14_REFERENCE,),
        ),
    ),
    provenance=ModelProvenance.ASSUMED,
    source_refs=(BSSA14_REFERENCE,),
    excluded=NOT_VERIFIED,
    notes=(
        "ASSUMED equal weights: no published weighting of the Q-region choice for the Himalaya "
        "was found, and the region's crustal attenuation is itself contested, so equal weights "
        f"state that rupture cannot choose between them. {LOWER_BOUND_NOTE}"
    ),
)

TREES: dict[str, GsimLogicTree] = {ACTIVE_SHALLOW_CRUST_Q.id: ACTIVE_SHALLOW_CRUST_Q}


class GsimLogicTreeError(KeyError):
    """The requested logic tree is not one rupture ships."""


def build(tree_id: str) -> GsimLogicTree:
    """The logic tree registered under ``tree_id``."""
    try:
        return TREES[tree_id]
    except KeyError as exc:
        known = ", ".join(sorted(TREES))
        msg = f"unknown GSIM logic tree {tree_id!r}; rupture ships {known}"
        raise GsimLogicTreeError(msg) from exc


def names() -> tuple[str, ...]:
    return tuple(sorted(TREES))


def gsim_logic_tree_nrml(tree: GsimLogicTree) -> str:
    """The tree as an OpenQuake ``gsim_logic_tree.xml`` (NRML 0.4).

    This is what the engine reads when it is asked for more than one GSIM; the branch ids, the
    weights and the tectonic region type are the same objects the native engine mixes, so the two
    paths cannot drift apart by editing one of them.
    """
    branches = "\n".join(
        f'        <logicTreeBranch branchID="{branch.id}">\n'
        f"          <uncertaintyModel>{branch.gsim}</uncertaintyModel>\n"
        f"          <uncertaintyWeight>{branch.weight:.10g}</uncertaintyWeight>\n"
        f"        </logicTreeBranch>"
        for branch in tree.branches
    )
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<nrml xmlns:gml="http://www.opengis.net/gml"\n'
        '      xmlns="http://openquake.org/xmlns/nrml/0.4">\n'
        f'  <logicTree logicTreeID="{tree.id}">\n'
        '    <logicTreeBranchSet uncertaintyType="gmpeModel" branchSetID="bs1"\n'
        f'                        applyToTectonicRegionType="{tree.tectonic_region}">\n'
        f"{branches}\n"
        "    </logicTreeBranchSet>\n"
        "  </logicTree>\n"
        "</nrml>\n"
    )
