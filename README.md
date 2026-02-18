# Auto Trading Pro

Sistema de trading automatico multi-broker y event-driven.

Automatic multi-broker trading platform with event-driven architecture.

## Estado / Status

- `Module 0 (Core Foundation)`: implemented and tested.
- `Module 1 (Data Layer)`: implemented with mock-first testing, storage, normalization, validation, resampling, fallback routing, and optional runtime integration.

## Arquitectura / Architecture

- `core/`: event bus, event models, config, plugin loading, logging, journal, snapshots.
- `data/`: connectors, normalizer, validator, resampler, timezone logic, asset detection/classification, fallback manager, feed manager.
- `storage/`: parquet history store, sqlite metadata/quality store, cache manager, repository facade.
- `strategies/`: strategy plugins.
- `config/`: YAML runtime config.
- `tests/`: unit + integration tests.

## Requisitos / Requirements

- Python `3.11+`
- Windows, Linux, or macOS (real broker connectors are optional and availability-aware).

## Instalacion / Installation

```bash
python -m pip install -e .[dev,data,storage,connectors,watch]
```

Minimal core only:

```bash
python -m pip install -e .[dev]
```

## Configuracion / Configuration

1. Copy values from `.env.example`.
2. Edit YAML files in `config/`:
- `config/system.yaml`
- `config/brokers.yaml`
- `config/strategies.yaml`

Default data layer run uses `mock_dev` connector from `config/brokers.yaml`.

## Ejecutar / Run

Normal run:

```bash
python main.py
```

Smoke run (auto-stop validation):

```bash
python main.py --smoke-seconds 8
```

## Tests & Quality

```bash
python -m pytest tests/ -v
python -m ruff check .
python -m mypy core data storage
```

## Modulo 1 Highlights

- Unified `DataConnector` contract.
- `MockConnector` with injectable bars/ticks, latency, and error simulation.
- `Normalizer` for broker payload mapping.
- `DataValidator` for gaps, duplicates, corruption, outliers.
- `Resampler` for tick->OHLCV and timeframe upsampling.
- `ParquetStore` monthly partitioning + deduplication.
- `SQLiteStore` for metadata, quality reports, and last prices.
- `DataRepository` as the single historical data access point.
- `FeedManager` orchestration with connector health and fallback routing.

## Seguridad / Security

- Never commit real credentials.
- Logging helpers redact sensitive keys (`password`, `token`, `secret`, `api_key`, etc.).
- Tests run against `MockConnector` (no real broker connectivity required).

## Roadmap

- Module 2: Indicator engine consuming `DataRepository.get_ohlcv(...)`.
- Broader production-grade implementations for MT5/IQOption/IOL/FXPro/TradingView/NinjaTrader.
- Postgres production store implementation.

## Contribucion / Contributing

1. Create a feature branch.
2. Keep type hints and tests updated.
3. Run quality checks before PR.
4. Prefer mock-first tests for connector behavior.

## Licencia / License

Private/internal project by default (set your license policy before publishing).
