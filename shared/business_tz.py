"""The single business timezone every date/time-sensitive calculation in this app
is anchored to — not the server process's own timezone (production runs in UTC),
not each viewer's browser timezone. This is a single-location business, so "today"
and "this month" should mean the same thing everywhere, matching the business's
own clock. See web/src/lib/datetime.ts for the frontend display counterpart.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("America/Chicago")


def business_now() -> datetime:
    """The current instant, expressed in the business's own timezone — for any
    "is this still the current month/day" check. Never use datetime.now() /
    pd.Timestamp.now() directly for that: those read the server process's own
    timezone (UTC in production), which disagrees with the business's actual
    calendar for several hours around every day/month boundary."""
    return datetime.now(BUSINESS_TIMEZONE)
