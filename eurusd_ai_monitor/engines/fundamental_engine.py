"""Public fundamental-intelligence API.

The initial implemented specialist is the point-in-time cross-Atlantic
inflation and unemployment assessment. Additional fundamental dimensions
can be added behind this stable module boundary as verified sources mature.
"""

from .macro_fundamentals_engine import (
    MACRO_FUNDAMENTALS_VERSION,
    MacroFundamentalsEngine,
)

__all__ = ["MACRO_FUNDAMENTALS_VERSION", "MacroFundamentalsEngine"]
