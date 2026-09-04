# ADR-0038: The automated shutdown depends on warning time, and the anchored pair crosses

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Extends:** ADR-0025 (intervention models), which remains in force except as amended here

## Context

Two things that only became visible once the loss layer was run over thousands of small events
rather than two large ones.

**1. The shutdown had no timing.** ADR-0025 modelled `automated_shutdown` as subtracting a flat
fraction (default 15 %, assumed, a request parameter) of the powerhouse component's loss in every
realisation. `Intervention.lead_time_minutes` existed in the domain and nothing read it. A measure
whose whole value depends on getting an alert to a machine before the shaking arrives was modelled
as if the alert always arrived. For a corridor sitting directly above the Main Himalayan Thrust
that is not a small simplification: the source is under the plant.

**2. HAZUS's anchored/unanchored pair crosses.** ADR-0025 chose the retrofit model precisely
because HAZUS publishes a *pair* of curves rather than a median shift. Over an event set full of
small earthquakes the pair turns out not to be monotone.

## Decision

### 1. The shutdown fires only where it can

`rupture.risk.event_based.ShutdownTrigger` makes the measure conditional on two things, evaluated
per site per realisation:

- **the trip fires** — the realised ground motion at the site exceeds `threshold_g`;
- **there is time** — `hypocentral distance / S-wave speed - (detection and dissemination latency
  + the machinery's own stopping time)` is positive.

The stated defaults are 0.05 g, 3.5 km/s, 5 s and 10 s. **None of the four is a published figure**;
all four are request parameters (`trigger_g`, `s_wave_km_s`, `latency_s`, `stopping_time_s`) and
`ShutdownTrigger.describe()` says so in the response's `assumptions` on every run that uses it.
The 15 % avoided fraction of ADR-0025 is unchanged and still assumed; it is now applied only where
the trigger fires in time.

The result is a finding, not a formality:

| Scenario | Hypocentral distance to the corridor | Warning time | Avoided |
|---|---|---|---|
| `gorkha-2015-repeat` | 56-75 km | +1 to +6 s at all 14 sites | USD 52.5 M |
| `mht-m8-hypothetical` | 29-41 km, 10 km deep | **-3 to -7 s at all 14 sites** | **USD 0** |

For the rupture this corridor most needs to worry about, an alert-triggered shutdown is worth
nothing, and the model now says so instead of crediting it with 15 % of the powerhouse loss. The
same run with a consumer's own faster numbers (1 s latency, 1 s stop, 0.01 g trip) puts all 14
sites back in time, which is the point of the parameters being in the request.

The reference point is the **origin**: the latency covers detection and dissemination from the
source, so this models an alert from a regional network, not an on-site P-wave sensor at each
plant. A per-plant on-site trigger would have a different, shorter geometry and is not modelled.

### 2. A negative avoided loss in a catalogue is reported, not suppressed

HAZUS's anchored generation-facility curve for plants under 100 MW is fractionally **worse** than
its unanchored counterpart between about 0.006 g and 0.051 g, by at most 0.02 % of plant value.
That is a property of the published pair — `docs/RISK.md` and a test in
`tests/unit/risk/test_curves.py` pin the crossing so it cannot silently move — and it means a
synthetic year containing only very small events comes out marginally worse with the retrofit in
place.

`event_based.avoided_annual_loss` therefore:

- does **not** treat a negative difference in an individual catalogue as a bug;
- **refuses** a negative *expected* annual figure, raising rather than reporting an avoided loss of
  zero, because that is a measure that does not work and the contract's `MoneyRange` cannot state
  it;
- when some catalogues are negative, reports the share and the worst shortfall in the outcome's
  `assumptions`, and says that `MoneyRange` cannot be negative so the interval was truncated at
  zero and this note carries what the truncation hid.

The scenario path's original rule ("a negative avoided loss is a bug") was written for two large
ruptures where it holds, and it still holds there. The event-based path meets the crossing and
handles it.

## Consequences

- `automated_shutdown` is no longer a measure that always looks worth something. Where it is worth
  nothing, the answer is zero and the reason is in the response.
- Four new assumed parameters exist. They are all named, all overridable, and all reported. That is
  four more assumptions than before, which is the honest cost of modelling the thing at all rather
  than a flat fraction.
- ADR-0025's account of `automated_shutdown` is amended by this ADR; the rest of ADR-0025 stands.

## Alternatives considered

- **A per-plant on-site P-wave trigger.** Rejected for this pass: it needs a P-to-S separation at
  each site and a sensor model, and neither is sourced. It is the more favourable model for this
  corridor and its absence makes the reported avoided loss a lower estimate; recorded rather than
  assumed away.
- **Clamp negative catalogue differences to zero silently.** Rejected. It would hide a real
  property of a published fragility pair, and hiding it is exactly the failure the pair was chosen
  to avoid.
- **Drop the retrofit's small-event penalty by flooring the pair.** Rejected: editing a published
  curve to make a measure look monotone is fabrication.
