"""Built-in signal strategies."""

from signals.strategies.base import SignalStrategy
from signals.strategies.investment_fundamental import InvestmentFundamentalStrategy
from signals.strategies.mean_reversion import MeanReversionStrategy
from signals.strategies.momentum_breakout import MomentumBreakoutStrategy
from signals.strategies.range_scalp import RangeScalpStrategy
from signals.strategies.scalping_reversal import ScalpingReversalStrategy
from signals.strategies.swing_composite import SwingCompositeStrategy
from signals.strategies.trend_following import TrendFollowingStrategy

__all__ = [
    "InvestmentFundamentalStrategy",
    "MeanReversionStrategy",
    "MomentumBreakoutStrategy",
    "RangeScalpStrategy",
    "ScalpingReversalStrategy",
    "SignalStrategy",
    "SwingCompositeStrategy",
    "TrendFollowingStrategy",
]
