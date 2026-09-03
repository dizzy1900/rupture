"""Turning installed capacity into a replacement value, and saying exactly where the number came
from.

The corridor's exposure is published as *capacity* (MW), which is not money. Converting it needs a
cost basis, and a cost basis that is invented is worse than no valuation at all, so this module
carries exactly one published figure and is explicit about what it does and does not support.

**The published figure.** IRENA (2024), *Renewable power generation costs in 2023*, International
Renewable Energy Agency, Abu Dhabi (ISBN 978-92-9260-621-3): "the global weighted average total
installed cost of new hydropower projects decreased from USD 3 053/kW to USD 2 806/kW - a fall of
8 %". rupture uses **USD 2 806/kW in 2023 USD** as the central unit cost.

**What is assumed, and is labelled as assumed.** The interval around that figure is not published
dispersion. IRENA's number is a *global* weighted average of *newly commissioned greenfield*
projects; the Trishuli corridor's plants are Himalayan run-of-river schemes in a country whose
projects are widely reported as costing more than the global average, and post-earthquake
reinstatement is not the same activity as greenfield construction. rupture therefore applies a
documented +/- 40 % band (ADR-0025) and marks every figure derived from it
``ModelProvenance.ASSUMED`` with ``ConfidenceTier.LOW``. The central value is sourced; the
interval is a judgement, and calling it anything else would be the fabrication the non-negotiables
forbid.

**What has no basis at all.** Bridges, border posts and settlements in the corridor carry no
verified replacement cost here. They are kept in the portfolio at value zero so they still appear
in the damage decomposition, and every report says how many assets that is and that they
contribute nothing to the loss figure. Inventing a number for them would make the portfolio total
look complete when it is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from rupture.domain.money import ConfidenceTier, ModelProvenance, MoneyRange

IRENA_SOURCE_REF = (
    "IRENA (2024), Renewable power generation costs in 2023, International Renewable Energy "
    "Agency, Abu Dhabi, ISBN 978-92-9260-621-3 - global weighted average total installed cost of "
    "new hydropower projects, USD 2 806/kW (2023 USD)"
)
CENTRAL_USD_PER_KW = 2806.0
PRICE_YEAR = 2023
CURRENCY = "USD"
INTERVAL_FACTOR_LOW = 0.6
INTERVAL_FACTOR_HIGH = 1.4
KW_PER_MW = 1000.0

INTERVAL_ASSUMPTION = (
    "the +/- 40 % band around the IRENA central figure is an assumption (ADR-0025), not a "
    "published dispersion: IRENA's figure is a global weighted average for newly commissioned "
    "greenfield plant, and reinstatement cost in the Nepal Himalaya is neither"
)
NO_BASIS_NOTE = (
    "no verified replacement-cost basis for this asset class; carried at value zero so it appears "
    "in the damage decomposition without inflating the loss figure"
)

VALUED_ASSET_TYPES: frozenset[str] = frozenset({"hydropower_plant"})
"""Asset types rupture can price. Everything else is carried at zero, loudly."""


@dataclass(frozen=True, slots=True)
class HydropowerCostBasis:
    """Capacity to replacement value, with the source and the assumption both attached."""

    usd_per_kw: float = CENTRAL_USD_PER_KW
    price_year: int = PRICE_YEAR
    currency: str = CURRENCY
    source_ref: str = IRENA_SOURCE_REF
    low_factor: float = INTERVAL_FACTOR_LOW
    high_factor: float = INTERVAL_FACTOR_HIGH

    def best(self, capacity_mw: float) -> float:
        """Central replacement value for a plant of this installed capacity."""
        return capacity_mw * KW_PER_MW * self.usd_per_kw

    def money(self, capacity_mw: float, *, basis: str) -> MoneyRange:
        """The value as an interval, marked assumed because the interval is assumed."""
        central = self.best(capacity_mw)
        return MoneyRange(
            low=central * self.low_factor,
            high=central * self.high_factor,
            best=central,
            currency=self.currency,
            price_year=self.price_year,
            basis=basis,
            confidence=ConfidenceTier.LOW,
            provenance=ModelProvenance.ASSUMED,
            source_refs=(self.source_ref,),
        )

    def describe(self) -> str:
        return (
            f"{self.usd_per_kw:,.0f} {self.currency}/kW ({self.price_year} {self.currency}), "
            f"central figure published; interval +/-"
            f"{(self.high_factor - 1.0) * 100:.0f} % assumed"
        )


DEFAULT_BASIS = HydropowerCostBasis()
