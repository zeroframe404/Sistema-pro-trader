"""HTML/PDF report generation for backtest outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backtest.backtest_models import BacktestMetrics, BacktestResult, BacktestTrade


class ReportGenerator:
    """Render backtest reports in HTML and PDF formats."""

    def __init__(self, template_dir: Path) -> None:
        self._template_dir = template_dir

    def generate_html(self, result: BacktestResult, output_path: Path) -> Path:
        """Generate report HTML with embedded charts and summary tables."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        template_text = self._load_template()
        verdict_text, verdict_color = self._render_verdict(result.metrics)
        data = {
            "result": result,
            "metrics": result.metrics,
            "verdict_text": verdict_text,
            "verdict_color": verdict_color,
            "equity_chart": self._build_equity_chart(result),
            "drawdown_chart": self._build_drawdown_chart(result),
            "monthly_returns_chart": self._build_monthly_returns_chart(result),
            "mae_mfe_chart": self._build_mae_mfe_chart(result.trades),
            "trades_json": json.dumps([trade.model_dump(mode="json") for trade in result.trades]),
        }

        try:
            from jinja2 import Environment, FileSystemLoader

            env = Environment(loader=FileSystemLoader(str(self._template_dir)))
            template = env.from_string(template_text)
            html = template.render(**data)
        except Exception:  # noqa: BLE001
            html = self._fallback_html(result, verdict_text, verdict_color, data)

        output_path.write_text(html, encoding="utf-8")
        return output_path

    def generate_pdf(self, result: BacktestResult, output_path: Path) -> Path:
        """Render PDF from HTML using weasyprint, or fallback to matplotlib."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        html_path = output_path.with_suffix(".html")
        self.generate_html(result, html_path)
        try:
            from weasyprint import HTML

            HTML(filename=str(html_path)).write_pdf(str(output_path))
            return output_path
        except Exception:  # noqa: BLE001
            try:
                import matplotlib.pyplot as plt

                fig = plt.figure(figsize=(8.27, 11.69))
                fig.text(0.1, 0.95, "Backtest Report", fontsize=16, weight="bold")
                fig.text(0.1, 0.90, f"Strategy: {', '.join(result.config.strategy_ids)}", fontsize=10)
                fig.text(0.1, 0.87, f"Symbols: {', '.join(result.config.symbols)}", fontsize=10)
                fig.text(0.1, 0.84, f"Profit factor: {result.metrics.profit_factor:.3f}", fontsize=10)
                fig.text(0.1, 0.81, f"Sharpe: {result.metrics.sharpe_ratio:.3f}", fontsize=10)
                fig.text(0.1, 0.78, f"Max DD: {result.metrics.max_drawdown_pct:.2f}%", fontsize=10)
                fig.savefig(output_path, format="pdf")
                plt.close(fig)
            except Exception:  # noqa: BLE001
                output_path.write_bytes(b"%PDF-1.4\n% Backtest report fallback\n")
            return output_path

    def _build_equity_chart(self, result: BacktestResult) -> str:
        points = [{"x": ts.isoformat(), "y": value} for ts, value in result.equity_curve]
        return self._plotly_json(
            title="Equity Curve",
            x=[point["x"] for point in points],
            y=[point["y"] for point in points],
            chart_type="line",
        )

    def _build_drawdown_chart(self, result: BacktestResult) -> str:
        points = [{"x": ts.isoformat(), "y": value} for ts, value in result.drawdown_curve]
        return self._plotly_json(
            title="Drawdown Curve",
            x=[point["x"] for point in points],
            y=[point["y"] for point in points],
            chart_type="area",
        )

    def _build_monthly_returns_chart(self, result: BacktestResult) -> str:
        months = list(result.metrics.monthly_returns.keys())
        values = [result.metrics.monthly_returns[key] for key in months]
        return self._plotly_json(title="Monthly Returns", x=months, y=values, chart_type="bar")

    def _build_mae_mfe_chart(self, trades: list[BacktestTrade]) -> str:
        x = [trade.max_adverse_excursion for trade in trades]
        y = [trade.max_favorable_excursion for trade in trades]
        return self._plotly_json(title="MAE/MFE", x=x, y=y, chart_type="scatter")

    def _render_verdict(self, metrics: BacktestMetrics) -> tuple[str, str]:
        if (
            metrics.sharpe_ratio > 1.0
            and metrics.profit_factor > 1.3
            and metrics.max_drawdown_pct < 20.0
        ):
            return "System viable", "green"
        if metrics.sharpe_ratio > 0.5 and metrics.profit_factor > 1.0:
            return "System marginal", "orange"
        return "System not viable", "red"

    def _plotly_json(
        self,
        *,
        title: str,
        x: list[Any],
        y: list[Any],
        chart_type: str,
    ) -> str:
        try:
            import plotly.graph_objects as go

            if chart_type == "bar":
                figure = go.Figure(data=[go.Bar(x=x, y=y)])
            elif chart_type == "area":
                figure = go.Figure(data=[go.Scatter(x=x, y=y, fill="tozeroy")])
            elif chart_type == "scatter":
                figure = go.Figure(data=[go.Scatter(x=x, y=y, mode="markers")])
            else:
                figure = go.Figure(data=[go.Scatter(x=x, y=y)])
            figure.update_layout(title=title)
            return str(figure.to_json())
        except Exception:  # noqa: BLE001
            return json.dumps({"title": title, "x": x, "y": y, "type": chart_type})

    def _load_template(self) -> str:
        template_path = self._template_dir / "report.html.jinja2"
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
        return self._fallback_template()

    def _fallback_template(self) -> str:
        return """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Backtest Report</title></head>
<body>
<h1>Backtest Report</h1>
<p style="color: {{ verdict_color }};"><strong>{{ verdict_text }}</strong></p>
<p>Symbol: {{ result.config.symbols|join(', ') }}</p>
<p>Strategy: {{ result.config.strategy_ids|join(', ') }}</p>
<h2>Metrics</h2>
<pre>{{ metrics.model_dump_json(indent=2) }}</pre>
<h2>Charts</h2>
<div id="equity">{{ equity_chart }}</div>
<div id="drawdown">{{ drawdown_chart }}</div>
<div id="monthly">{{ monthly_returns_chart }}</div>
<div id="mae_mfe">{{ mae_mfe_chart }}</div>
<script>window.plotly='plotly';</script>
</body>
</html>
"""

    def _fallback_html(
        self,
        result: BacktestResult,
        verdict_text: str,
        verdict_color: str,
        data: dict[str, Any],
    ) -> str:
        _ = data
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Backtest Report</title></head><body>"
            "<h1>Backtest Report</h1>"
            f"<p style='color:{verdict_color};'><strong>{verdict_text}</strong></p>"
            f"<p>Symbol: {', '.join(result.config.symbols)}</p>"
            f"<p>Strategy: {', '.join(result.config.strategy_ids)}</p>"
            "<h2>Metrics</h2>"
            f"<pre>{result.metrics.model_dump_json(indent=2)}</pre>"
            "<script>window.plotly='plotly';</script>"
            "</body></html>"
        )


__all__ = ["ReportGenerator"]
