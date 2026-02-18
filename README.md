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

## Module Status

- Module 0: Core Foundation - Complete
- Module 1: Data Layer - Complete
- Module 2: Indicators + Regime - Complete
- Module 3: Signal Engine - Complete
- Module 4: Risk + OMS - Complete

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
- Module 5: Portfolio/Backoffice Extensions - Planned
- Module 6+: Paper/Live/Backtest/UI expansion - Planned

## Contributing

- Ejecutar `ruff`, `mypy` y `pytest` antes de abrir PR.
- Mantener docstrings y type hints en APIs publicas.
- Evitar import cycles entre modulos.

## License

Private/internal by default.
