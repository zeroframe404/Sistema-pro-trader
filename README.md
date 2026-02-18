# Auto Trading Pro

Sistema de trading automatico multi-broker, multi-activo y event-driven.

Multi-broker, multi-asset, event-driven automated trading platform.

## Vision / Vision

- ES: construir una plataforma modular para data, indicadores, regimen, senales, riesgo y ejecucion.
- EN: build a modular platform for data, indicators, market regime, signals, risk, and execution.

## Module Status

- Module 0: Core Foundation (event bus, config, plugins, logging, snapshots, journal)
- Module 1: Data Layer (connectors, normalization, validation, resampling, storage, repository)
- Module 2: Indicators + Regime (technical engine, market regime detection, validation scripts)

## Architecture

- `core/`: event bus, event types/models, config loader/editor, logging, plugin manager, registry.
- `data/`: connector contracts + wrappers, feed manager, normalizer, validator, fallback.
- `storage/`: parquet/sqlite/cache + unified `DataRepository`.
- `indicators/`: 30+ indicators across trend/momentum/volatility/volume/patterns.
- `regime/`: trend/volatility/liquidity regime + market conditions + sessions + news windows.
- `tests/`: unit, integration, and validation scripts.
- `scripts/`: sample-data bootstrap and module 2 demo runner.

## Requirements

- Python 3.11+
- Optional native dependencies: TA-Lib (if available, auto-used; otherwise fallback backend is used).

## Installation

Base + dev + data + storage + connectors + module 2 extras:

```bash
python -m pip install -r requirements.txt
```

Equivalent editable install:

```bash
python -m pip install -e .[dev,data,parquet,storage,connectors,watch,indicators,validation]
```

## Configuration

Main YAML files:

- `config/system.yaml`
- `config/brokers.yaml`
- `config/strategies.yaml`
- `config/indicators.yaml`

Environment overrides use `ATP_` prefix and `__` for nested paths.
Example:

```bash
set ATP_SYSTEM__ENVIRONMENT=development
set ATP_INDICATORS__REGIME__ENABLED=true
```

## Quickstart

1) Generate/download sample datasets:

```bash
python scripts/download_sample_data.py
```

2) Run module 2 demo:

```bash
python scripts/run_module2_demo.py --symbol EURUSD --timeframe H1
python scripts/run_module2_demo.py --symbol BTCUSD --timeframe H1
python scripts/run_module2_demo.py --all-assets
```

3) Run full app smoke check:

```bash
python main.py --smoke-seconds 8
```

## Quality and Validation

Static checks:

```bash
python -m ruff check .
python -m mypy core data storage indicators regime
```

Automated tests:

```bash
python -m pytest tests/ -v --tb=short
```

Indicator/regime validation:

```bash
python tests/validation/validate_indicators.py
python tests/validation/validate_regime.py
python tests/validation/generate_validation_charts.py
```

## Module 2 Highlights

Trend:

- SMA, EMA, WMA, DEMA, TEMA, HMA
- ADX (+DI/-DI), SuperTrend, Ichimoku, Parabolic SAR

Momentum:

- RSI, MACD, Stochastic, StochRSI, CCI, MFI, Williams %R

Volatility:

- ATR, Bollinger Bands (+%B + bandwidth), Keltner Channel, VIX proxy

Volume:

- OBV, VWAP (UTC daily reset), Volume Profile, CMF

Patterns:

- Candlestick detector, chart pattern heuristics, support/resistance pivots

Regime:

- Trend/volatility/liquidity classification
- Hurst + autocorrelation + ADX/ATR/EMA signals
- Tradeability checks (`spread_spike`, `low_volume`, `bad_session`, `news_window`, `price_freeze`)

## Security

- Never commit real credentials.
- Keep secrets in `.env` only.
- Logging redacts sensitive keys (`password`, `token`, `secret`, `api_key`, etc.).

## Notes about Connectors

- Real connector wrappers are availability-aware and degrade safely when dependencies are missing.
- `MockConnector` is the recommended default for tests and CI.
- Module 2 validation is "mixed strict": it tries network data first, then deterministic local fallback.

## Roadmap

- Module 3: Signals and ensemble scoring
- Module 4: Fundamental/news deep integration
- Module 5: Risk engine
- Module 6: OMS/execution adapters
- Module 7+: paper/live/backtest/UI expansion

## License

Private/internal by default. Define your public license policy before publishing.
