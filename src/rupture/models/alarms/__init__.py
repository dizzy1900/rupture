"""Alarm models: the ``AlarmSet`` arm's producers.

Two live here and neither is a challenger. They exist so that the alarm scorer has something
adversarial to be tested against: a trivial clustering rule that *should* look skilful against a
weak reference, and any fitted rate forecast reinterpreted as an alarm function.
"""

from rupture.models.alarms.from_forecast import alarm_from_forecast_grid
from rupture.models.alarms.recent_large import (
    RECENT_LARGE_MODEL_ID,
    RecentLargeParameters,
    recent_large_alarm,
)

__all__ = [
    "RECENT_LARGE_MODEL_ID",
    "RecentLargeParameters",
    "alarm_from_forecast_grid",
    "recent_large_alarm",
]
