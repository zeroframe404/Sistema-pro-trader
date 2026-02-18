from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from backtest.backtest_models import BacktestConfig, BacktestMetrics, BacktestMode, BacktestResult
from backtest.report_generator import ReportGenerator
from data.asset_types import AssetClass


def _result() -> BacktestResult:
    config = BacktestConfig(
        strategy_ids=["trend_following"],
        symbols=["EURUSD"],
        brokers=["mock_dev"],
        timeframes=["H1"],
        asset_classes=[AssetClass.FOREX],
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 2, 1, tzinfo=UTC),
        mode=BacktestMode.SIMPLE,
    )
    metrics = BacktestMetrics(
        total_trades=20,
        win_rate=0.6,
        sharpe_ratio=1.2,
        profit_factor=1.4,
        max_drawdown_pct=10.0,
        monthly_returns={"2024-01": 3.2},
    )
    eq = [(datetime(2024, 1, 1, tzinfo=UTC), 10000.0), (datetime(2024, 1, 2, tzinfo=UTC), 10050.0)]
    dd = [(datetime(2024, 1, 1, tzinfo=UTC), 0.0), (datetime(2024, 1, 2, tzinfo=UTC), 1.0)]
    return BacktestResult(config=config, metrics=metrics, equity_curve=eq, drawdown_curve=dd, trades=[])


def test_generate_html_contains_symbol_and_plotly(tmp_path: Path) -> None:
    generator = ReportGenerator(template_dir=Path("backtest/templates"))
    result = _result()
    output = generator.generate_html(result, tmp_path / "report.html")
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "EURUSD" in text
    assert "plotly" in text.lower()


def test_render_verdict_good_and_bad() -> None:
    generator = ReportGenerator(template_dir=Path("backtest/templates"))
    good = BacktestMetrics(sharpe_ratio=1.2, profit_factor=1.5, max_drawdown_pct=10.0)
    bad = BacktestMetrics(sharpe_ratio=0.1, profit_factor=0.8, max_drawdown_pct=40.0)
    verdict_good = generator._render_verdict(good)  # noqa: SLF001
    verdict_bad = generator._render_verdict(bad)  # noqa: SLF001
    assert verdict_good[0] == "System viable"
    assert verdict_bad[0] == "System not viable"


def test_generate_pdf_file_created(tmp_path: Path) -> None:
    generator = ReportGenerator(template_dir=Path("backtest/templates"))
    result = _result()
    output = generator.generate_pdf(result, tmp_path / "report.pdf")
    assert output.exists()
