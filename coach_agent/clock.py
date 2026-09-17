"""The one place that decides what time it is.

Split out of tools.py when the food log arrived: the log needs the same clock the
clock tool hands the model, and tools.py imports the log — so the timezone had to
live somewhere neither of them owns, or the import went in a circle.

The zone is hardcoded rather than read from the host on purpose. The EC2 instance
runs in UTC, and a naive `datetime.now()` there returns a time that is wrong by
two or three hours without raising anything. In Phase 5 this becomes per-user.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Jerusalem")


def now_local() -> datetime:
    """Now, as an aware datetime in the coaching timezone."""
    return datetime.now(TIMEZONE)
