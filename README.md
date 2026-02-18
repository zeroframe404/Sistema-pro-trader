# Auto Trading Pro

Sistema de trading automatico multi-broker, multi-activo y event-driven.

Multi-broker, multi-asset, event-driven automated trading platform.

## Vision / Vision

- ES: plataforma modular para datos, indicadores, regimen, motor de senales, riesgo y ejecucion.
- EN: modular platform for data, indicators, market regime, signal engine, risk and execution.

## Features

- Event bus async (`asyncio`) con fallback Redis controlado.
- Configuracion YAML + Pydantic v2 + hot-reload y overrides `ATP_*`.
- Data layer con conectores reales/wrappers y `MockConnector` para CI.
- Indicadores + regimen (Modulo 2) con cache, fallback backend y validacion.
- Motor de senales multi-estrategia (Modulo 3) con ensemble ponderado.
- Decision en lenguaje natural por horizonte (`"2 horas"`, `"3 meses"`, `"1 ano"`).
- Explicacion detallada con razones y pesos.
- Anti-overtrading: cooldown, limite por ventana, pausa por perdidas consecutivas.
- Filtros de mercado: regimen, noticias, sesion, spread y correlacion.
- Gestion de riesgo institucional: position sizing (fixed, percent_risk, ATR, Kelly), drawdown limits y kill switch.
- OMS completo: ciclo de vida de orden, idempotencia, retry y reconciliacion broker vs estado interno.
- Paper trading production-ready: misma API de execution con fills simulados, slippage y comisiones configurables.
- Backtesting serio: walk-forward analysis, validacion OOS con purging/embargo y sin look-ahead bias.
- Optimizacion de parametros con score penalizado anti-overfit.
- Market replay a velocidad controlada para debugging historico.
- Shadow mode para validar decisiones en paralelo sin enviar ordenes reales.
- Reportes completos HTML/PDF con equity, drawdown, metrics y MAE/MFE.

## Module Status

- Module 0: Core Foundation - Complete
- Module 1: Data Layer - Complete
- Module 2: Indicators + Regime - Complete
- Module 3: Signal Engine - Complete
- Module 4: Risk + OMS - Complete
- Module 5: Backtesting + Replay + Shadow - Complete

## Architecture

- `core/`: event bus, events, config, logging, plugins, registry, snapshot, audit journal.
- `data/`: connectors, normalizer, validator, resampler, feed manager.
- `storage/`: parquet/sqlite/cache/postgres-stub + `DataRepository`.
- `indicators/`: trend, momentum, volatility, volume, patterns.
- `regime/`: regime detector, market conditions, sessions, news windows.
- `signals/`: signal models, ensemble, confidence, filters, anti-overtrading, strategies, engine.
- `tests/`: unit, integration, validation.
- `scripts/`: data bootstrap + module demos.

## Requirements

- Python 3.11+
- Optional native libs: TA-Lib (if missing, fallback backend is used)

## Installation

```bash
python -m pip install -r requirements.txt
```

Editable install with extras:

```bash
python -m pip install -e .[dev,data,parquet,storage,connectors,watch,indicators,validation,signals]
```

## Configuration

Main YAML files:

- `config/system.yaml`
- `config/brokers.yaml`
- `config/strategies.yaml`
- `config/indicators.yaml`
- `config/signals.yaml`
- `config/risk.yaml`

Environment overrides:

```bash
set ATP_SYSTEM__ENVIRONMENT=development
set ATP_SIGNALS__ENABLED=true
set ATP_SIGNALS__ENSEMBLE__METHOD=weighted_vote
```

## Quickstart

1. Download/generate sample data:

```bash
python scripts/download_sample_data.py
```

2. Run module 3 demo:

```bash
python scripts/run_module3_demo.py --symbol EURUSD --horizon "2 horas"
python scripts/run_module3_demo.py --symbol BTCUSD --horizon "1 semana"
python scripts/run_module3_demo.py --symbol GGAL --horizon "3 meses"
python scripts/run_module3_demo.py --all-assets
```

3. Run module 4 demo:

```bash
python scripts/run_module4_demo.py --scenario all
```

4. Smoke run:

```bash
python main.py --smoke-seconds 8
```

5. Module 5:

```bash
python scripts/run_backtest.py --strategy trend_following --symbol EURUSD --timeframe H1 --start 2023-01-01 --end 2024-01-01
python scripts/run_backtest.py --strategy trend_following --symbol EURUSD --timeframe H1 --start 2022-01-01 --end 2024-01-01 --mode walk_forward
python scripts/run_optimization.py --strategy trend_following --symbol EURUSD --timeframe H1 --start 2023-01-01 --end 2024-01-01 --params "rsi_period=7:30:1,ema_fast=5:50:5" --n-trials 25
python scripts/run_module5_demo.py --scenario all
```

## Motor de Senales

### API de alto nivel

```python
result = await signal_engine.get_decision_for_user(
    symbol="EURUSD",
    broker="mock_dev",
    horizon_input="2 horas",
)
print(result.display_decision)     # COMPRAR | VENDER | NO HAY INFO CLARA | NO OPERAR
print(result.confidence_percent)   # 0..100
print(result.ensemble.explanation) # explicacion en espanol
```

### Decisiones posibles

| Decision | Cuando |
|---|---|
| COMPRAR | Alta probabilidad de subida |
| VENDER | Alta probabilidad de caida |
| NO HAY INFO CLARA | Senales contradictorias o baja confianza |
| NO OPERAR | Mercado bloqueado por filtros/condiciones |

### Estrategias built-in

| Estrategia | Horizonte principal | Activos |
|---|---|---|
| `trend_following` | Intraday/Swing | Forex, crypto, ETF |
| `mean_reversion` | Scalp/Intraday | Forex, crypto |
| `momentum_breakout` | Intraday/Swing | Forex, crypto, equity |
| `scalping_reversal` | Scalp | Forex, crypto, binarias |
| `swing_composite` | Swing/Position | Equity, ETF, CEDEAR |
| `investment_fundamental` | Position/Investment | Equity, CEDEAR, bonos/ETF |
| `range_scalp` | Scalp | Forex, crypto |

### Horizontes soportados

- `"5 minutos"` -> `scalp` -> `M5`
- `"2 horas"` -> `intraday` -> `H1`
- `"3 semanas"` -> `swing` -> `D1`
- `"6 meses"` -> `position` -> `W1`
- `"2 anos"` -> `investment` -> `MN1`

## Gestion de Riesgo

### Position Sizing

| Metodo | Descripcion | Cuando usar |
|---|---|---|
| `fixed_units` | Tamano fijo | Testing |
| `fixed_amount` | Monto fijo en USD | Opciones binarias |
| `percent_equity` | % del equity total | Inversiones largas |
| `percent_risk` | % del equity como riesgo maximo | Default Forex/Cripto |
| `atr_based` | Riesgo en multiplos de ATR | Mercados volatiles |
| `kelly_fractional` | Kelly criterion fraccionado | Con historial de win rate |

### Limites Globales (configurables en `config/risk.yaml`)

```yaml
limits:
  max_daily_drawdown_pct: 3.0
  max_weekly_drawdown_pct: 7.0
  max_open_positions: 5
  max_exposure_per_symbol_pct: 10.0
  max_correlated_exposure_pct: 20.0
```

### Kill Switch

Se activa automaticamente cuando:
- Drawdown diario/semanal supera limite.
- Equity cae por debajo del umbral minimo.
- Errores API o latencia superan limites.
- Fill deviation o equity spike indica estado anomalo.
- Perdidas consecutivas superan el maximo configurado.

## OMS (Order Management)

```
Signal -> RiskManager -> OrderManager -> BrokerAdapter
           |                               |
      Kill Switch               paper | mt5 | iqoption | iol | fxpro | ccxt
```

Garantias del OMS:
- Idempotencia para evitar ordenes duplicadas.
- Retry con backoff exponencial en fallos transitorios.
- Reconciliacion periodica broker vs estado interno.
- Paper trading 1:1 con live a nivel API.

## Backtesting

### CLI rapida

```bash
# Backtest simple
python scripts/run_backtest.py --strategy trend_following --symbol EURUSD --timeframe H1 --start 2023-01-01 --end 2024-01-01

# Walk-forward
python scripts/run_backtest.py --strategy trend_following --symbol EURUSD --timeframe H1 --start 2022-01-01 --end 2024-01-01 --mode walk_forward

# Out-of-sample
python scripts/run_backtest.py --strategy mean_reversion --symbol BTCUSD --timeframe H1 --start 2022-01-01 --end 2024-01-01 --mode out_of_sample

# Optimization
python scripts/run_optimization.py --strategy trend_following --symbol EURUSD --timeframe H1 --start 2023-01-01 --end 2024-01-01 --params "rsi_period=7:30:1,ema_fast=5:50:5" --n-trials 25
```

### Metrics thresholds

| Metric | Description | Minimum |
|---|---|---|
| Profit Factor | gross_profit / gross_loss | > 1.30 |
| Sharpe Ratio | annualized risk-adjusted return | > 0.80 |
| Sortino Ratio | downside-risk-adjusted return | > 1.00 |
| Max Drawdown | peak-to-trough drop | < 25% |
| Calmar Ratio | CAGR / max_drawdown | > 1.00 |
| Ulcer Index | drawdown stress | < 5.0 |
| Expectancy | expected PnL per trade | > 0 |
| Win Rate | winner trades % | > 40% |

### Anti-overfitting

- Walk-forward rolling train/test windows.
- OOS split with purge/embargo between IS and OOS.
- Penalized optimizer score by complexity and instability.
- Degradation score tracks test_sharpe / train_sharpe.

### Market replay

```python
replayer = MarketReplayer(...)
await replayer.start(
    symbol="EURUSD",
    broker="mock_dev",
    timeframe="H1",
    start=datetime(2024, 1, 1, tzinfo=UTC),
    end=datetime(2024, 1, 8, tzinfo=UTC),
    speed=100.0,
)
```

### Shadow mode

```python
shadow = ShadowMode(signal_engine, risk_manager, fill_simulator, event_bus, logger)
await shadow.start()
metrics = shadow.get_shadow_metrics()
comparison = shadow.compare_with_live(live_trades)
```

## Quality and Validation

Static checks:

```bash
python -m ruff check .
python -m mypy core data storage indicators regime signals
```

Tests:

```bash
python -m pytest tests/ -v --tb=short
```

Validation scripts:

```bash
python tests/validation/validate_indicators.py
python tests/validation/validate_regime.py
python tests/validation/validate_signals.py
python tests/validation/validate_risk_limits.py
python tests/validation/generate_validation_charts.py
```

## Security

- Nunca commitear credenciales reales.
- Usar `.env` para secretos y mantener `.env` fuera de git.
- Redaccion de claves sensibles en logs (`password`, `token`, `secret`, `api_key`, etc.).

## Connectors Notes

- Conectores reales se cargan con deteccion de disponibilidad (`_available`) y degradacion segura.
- `MockConnector` es el conector recomendado para tests/CI.
- Las pruebas no dependen de credenciales reales de broker.

## Roadmap

- Module 0: Core Foundation - Complete
- Module 1: Data Layer - Complete
- Module 2: Indicators + Regime - Complete
- Module 3: Signal Engine - Complete
- Module 4: Risk + OMS - Complete
- Module 5: Backtesting + Replay + Shadow - Complete
- Module 6+: Paper/Live/Backtest/UI expansion - Planned

## Contributing

- Ejecutar `ruff`, `mypy` y `pytest` antes de abrir PR.
- Mantener docstrings y type hints en APIs publicas.
- Evitar import cycles entre modulos.

## License

Private/internal by default.
