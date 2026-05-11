"""Legacy parameter-driven algorithms (deprecated).

Kept for backwards compatibility with callers still using `algorithm: tick-chaser`
or `algorithm: timed-escalation`. New code should use intent-driven
`SmartOrderConfig(intent="standard"|"urgent")` and `intent_router`.

Importing this module registers `legacy:tick-chaser` and `legacy:timed-escalation`.
The original short names (`tick-chaser`, `timed-escalation`) remain registered for
one minor version, with a DeprecationWarning when looked up via the engine.
"""

from . import tick_chaser  # noqa: F401  -- registers legacy:tick-chaser
from . import timed_escalation  # noqa: F401  -- registers legacy:timed-escalation
