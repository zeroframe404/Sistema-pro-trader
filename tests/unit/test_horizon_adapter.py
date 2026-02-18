from __future__ import annotations

import pytest

from data.asset_types import AssetClass, TradingHorizon
from signals.horizon_adapter import HorizonAdapter


def test_horizon_mappings() -> None:
    adapter = HorizonAdapter()
    assert adapter.parse_horizon("5 minutos").horizon_class == TradingHorizon.SCALP
    assert adapter.parse_horizon("5 minutos").timeframe == "M5"

    assert adapter.parse_horizon("2 horas").horizon_class == TradingHorizon.INTRADAY
    assert adapter.parse_horizon("2 horas").timeframe == "H1"

    assert adapter.parse_horizon("3 semanas").horizon_class == TradingHorizon.SWING
    assert adapter.parse_horizon("3 semanas").timeframe == "D1"

    assert adapter.parse_horizon("6 meses").horizon_class == TradingHorizon.POSITION
    assert adapter.parse_horizon("6 meses").timeframe == "W1"

    assert adapter.parse_horizon("1 ano").horizon_class == TradingHorizon.INVESTMENT
    assert adapter.parse_horizon("1 ano").timeframe == "MN1"
    assert adapter.parse_horizon("1M").timeframe == "W1"


def test_invalid_horizon_raises_clear_error() -> None:
    adapter = HorizonAdapter()
    with pytest.raises(ValueError, match="Horizonte invalido"):
        adapter.parse_horizon("banana")


def test_binary_option_warns_for_long_horizon() -> None:
    adapter = HorizonAdapter()
    parsed = adapter.parse_horizon("3 dias", asset_class=AssetClass.BINARY_OPTION)
    assert parsed.warning is not None
