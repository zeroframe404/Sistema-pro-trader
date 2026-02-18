"""Human-readable explanation utilities for signal decisions."""

from __future__ import annotations

from signals.signal_models import EnsembleResult, SignalDirection


class SignalExplainer:
    """Build user-facing Spanish explanations for decisions."""

    def explain_full(self, ensemble: EnsembleResult) -> str:
        """Build detailed explanation with top reasons."""

        action = self._direction_text(ensemble.final_direction)
        reasons = ensemble.all_reasons[:5]
        if not reasons:
            return (
                f"Recomendacion: {action}. "
                f"Confianza {int(round(ensemble.final_confidence * 100))}%. "
                f"Sin razones suficientes en este momento."
            )

        rendered = [
            f"- {item.factor}: {item.description} (peso {int(round(item.weight * 100))}%)"
            for item in reasons
        ]
        filters = ", ".join(ensemble.filters_blocked) if ensemble.filters_blocked else "ninguno"
        return (
            f"Recomendamos {action} con confianza {int(round(ensemble.final_confidence * 100))}%. "
            f"Regimen actual {ensemble.regime.trend.value}/{ensemble.regime.volatility.value}. "
            f"Bloqueos activos: {filters}. Razones principales:\n" + "\n".join(rendered)
        )

    def explain_notification(self, ensemble: EnsembleResult) -> str:
        """Build compact notification text under 140 chars."""

        action = self._direction_text(ensemble.final_direction)
        base = (
            f"{ensemble.symbol} {ensemble.timeframe}: {action} "
            f"{int(round(ensemble.final_confidence * 100))}%"
        )
        if len(base) <= 140:
            return base
        return base[:137] + "..."

    def explain_no_trade(self, block_reason: str) -> str:
        """Build explicit no-trade explanation."""

        return f"No operar: mercado bloqueado por {block_reason}."

    def horizon_to_human(self, horizon: str) -> str:
        """Render compact horizon token to Spanish."""

        return _horizon_to_human(horizon)

    @staticmethod
    def _direction_text(direction: SignalDirection) -> str:
        if direction == SignalDirection.BUY:
            return "COMPRAR"
        if direction == SignalDirection.SELL:
            return "VENDER"
        if direction == SignalDirection.NO_TRADE:
            return "NO OPERAR"
        return "NO HAY INFO CLARA"


def _horizon_to_human(horizon: str) -> str:
    raw = horizon.strip()
    token = raw.lower()

    if token.endswith("mn"):
        amount = token[:-2]
        return f"{amount} mes" if amount == "1" else f"{amount} meses"
    if raw.endswith("M") and raw[:-1].isdigit():
        amount = raw[:-1]
        return f"{amount} mes" if amount == "1" else f"{amount} meses"
    if token.endswith("h"):
        amount = token[:-1]
        return f"{amount} hora" if amount == "1" else f"{amount} horas"
    if token.endswith("d"):
        amount = token[:-1]
        return f"{amount} dia" if amount == "1" else f"{amount} dias"
    if token.endswith("w"):
        amount = token[:-1]
        return f"{amount} semana" if amount == "1" else f"{amount} semanas"
    if token.endswith("y"):
        amount = token[:-1]
        return f"{amount} ano" if amount == "1" else f"{amount} anos"
    if token.endswith("m"):
        amount = token[:-1]
        return f"{amount} minuto" if amount == "1" else f"{amount} minutos"
    return horizon
