"""Natural-language horizon parser and timeframe mapper."""

from __future__ import annotations

import re
from dataclasses import dataclass

from data.asset_types import AssetClass, TradingHorizon


@dataclass(slots=True)
class HorizonSelection:
    """Parsed horizon details."""

    horizon_class: TradingHorizon
    timeframe: str
    canonical_horizon: str
    warning: str | None = None


class HorizonAdapter:
    """Map user horizon input to trading class/timeframe."""

    _TOKEN_RE = re.compile(r"^\s*(\d+)\s*([a-zA-Z]+)\s*$")

    def parse_horizon(
        self,
        horizon_input: str,
        asset_class: AssetClass | None = None,
    ) -> HorizonSelection:
        """Parse Spanish horizon text and return canonical selection."""

        raw = horizon_input.strip().lower()
        raw_original = horizon_input.strip()

        month_match = re.match(r"^\s*(\d+)\s*M\s*$", raw_original)
        if month_match is not None:
            amount = int(month_match.group(1))
            selection = HorizonSelection(
                horizon_class=TradingHorizon.POSITION,
                timeframe="W1",
                canonical_horizon=f"{amount}mn",
            )
            return self._attach_asset_warning(selection, asset_class)

        if raw == "manana":
            selection = HorizonSelection(
                horizon_class=TradingHorizon.SWING,
                timeframe="D1",
                canonical_horizon="1d",
            )
            return self._attach_asset_warning(selection, asset_class)

        normalized = (
            raw.replace("años", "anos")
            .replace("año", "ano")
            .replace("meses", "mes")
            .replace("semanas", "semana")
            .replace("horas", "hora")
            .replace("minutos", "minuto")
            .replace("dias", "dia")
        )

        shorthand = {
            "m": "minuto",
            "h": "hora",
            "d": "dia",
            "w": "semana",
            "mn": "mes",
            "y": "ano",
        }

        match = self._TOKEN_RE.match(normalized.replace(" ", ""))
        if match is not None:
            amount = int(match.group(1))
            unit = match.group(2)
            unit = shorthand.get(unit, unit)
        else:
            parts = normalized.split()
            if len(parts) < 2 or not parts[0].isdigit():
                raise ValueError(f"Horizonte invalido: {horizon_input}")
            amount = int(parts[0])
            unit = parts[1]
            for key, value in shorthand.items():
                if unit == key:
                    unit = value
                    break

        if unit.startswith("min"):
            selection = HorizonSelection(TradingHorizon.SCALP, "M5", f"{amount}m")
        elif unit.startswith("hora"):
            selection = HorizonSelection(TradingHorizon.INTRADAY, "H1", f"{amount}h")
        elif unit.startswith("dia"):
            timeframe = "H4" if amount <= 3 else "D1"
            horizon_class = TradingHorizon.SWING if amount >= 1 else TradingHorizon.INTRADAY
            selection = HorizonSelection(horizon_class, timeframe, f"{amount}d")
        elif unit.startswith("sem"):
            selection = HorizonSelection(TradingHorizon.SWING, "D1", f"{amount}w")
        elif unit.startswith("mes"):
            selection = HorizonSelection(TradingHorizon.POSITION, "W1", f"{amount}mn")
        elif unit.startswith("ano"):
            selection = HorizonSelection(TradingHorizon.INVESTMENT, "MN1", f"{amount}y")
        else:
            raise ValueError(f"Horizonte invalido: {horizon_input}")

        return self._attach_asset_warning(selection, asset_class)

    @staticmethod
    def _attach_asset_warning(
        selection: HorizonSelection,
        asset_class: AssetClass | None,
    ) -> HorizonSelection:
        if asset_class == AssetClass.BINARY_OPTION and selection.horizon_class != TradingHorizon.SCALP:
            selection.warning = "binary_option_long_horizon_not_recommended"
        return selection
