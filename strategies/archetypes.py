"""
Archetype strategies — re-exported from engine for backward compatibility.

All eight styles from the design document are available here.
CallingStationStrategy is preserved as an alias for LoosePassiveStrategy.
"""
from strategies.engine import (   # noqa: F401  (re-export)
    TightPassiveStrategy,
    TightAggressiveStrategy,
    LoosePassiveStrategy,
    LooseAggressiveStrategy,
    ManiacStrategy,
    NitStrategy,
    BalancedStrategy,
    TrapperStrategy,
)

# Legacy alias — calling station behaviour maps to loose-passive
CallingStationStrategy = LoosePassiveStrategy
