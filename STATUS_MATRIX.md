# STATUS MATRIX

## 1. Resumen Ejecutivo

El repositorio contiene un bot Python de detección de primas entre bStocks y acciones subyacentes. La suite estándar actual pasa: **26/26 pruebas** (`python -m unittest discover -v`). No hay un comando ni una configuración de build identificables para este proyecto.

No es posible determinar alineación con el Plan Maestro aprobado, estados de sus fases ni aprobaciones: no se encontró dicho plan. Tampoco se encontraron ADR. Sí hay discrepancias verificables entre la documentación de integración/demo y el código: el flujo LIVE documentado no carga porque importa funciones que no existen en `executor.py`, y los métodos de Trading API que invoca no están implementados en `binance_web3_api.py`. Por ello, la auditoría se detiene antes de declarar una próxima fase.

## 2. Matriz de fases

No se puede enumerar la matriz de todas las fases: el Plan Maestro aprobado no está presente en el repositorio. La fila siguiente registra esta limitación de auditoría, no una fase inferida.

| Fase | Objetivo | Estado | check | build | Aprobada |
|------|----------|---------|-------|-------|----------|
| No verificable: Plan Maestro ausente | No consta en la documentación disponible | ⚠ Requiere revisión | ✅ 26/26 pruebas | ❌ Sin configuración de build | No verificable |

## 3. Documentación asociada

Documentos existentes considerados:

- [README.md](README.md): propósito, arquitectura resumida, decisiones técnicas declaradas, pruebas, limitaciones y roadmap. Describe el camino principal como construcción y simulación, y afirma que no hay firma ni ejecución real.
- [BINANCE_WEB3_INTEGRATION.md](BINANCE_WEB3_INTEGRATION.md): arquitectura de integración, endpoints y flujos DRY/LIVE; describe operaciones LIVE que no corresponden a los símbolos actualmente disponibles en el código.
- [VALIDATION_REPORT.md](VALIDATION_REPORT.md): resultados DRY y endpoints, con una conclusión de integración E2E lista que no concuerda con el estado importable actual del demo.
- [DEMO_CHECKLIST.md](DEMO_CHECKLIST.md): requisitos y pasos de demostración LIVE; presupone funciones de ejecución que no están presentes en el código actual.

No se localizó un Plan Maestro aprobado ni documentos ADR. Los documentos de demo y validación existentes no sustituyen al Plan Maestro ni a los ADR.

## 4. ADR relacionados

No se encontraron ADR en el repositorio; por tanto, no hay ADR cuya implementación pueda confirmarse ni relacionarse con archivos de código. La tabla “Key Technical Decisions” de [README.md](README.md) enumera decisiones, pero no es un ADR ni aporta registro de estado, contexto y consecuencias propio de un ADR.

## 5. Componentes implementados

| Categoría | Componentes observados |
|-----------|------------------------|
| layouts | No aplica: no hay interfaz web ni sistema de layouts. |
| dominios | `strategy.py` (evaluación de oportunidad y rentabilidad); `data_fetcher.py`, `stock_price_fetcher.py` y `web3_price_fetcher.py` (precios y fuentes); `backtest.py` (backtest). |
| navegación | No aplica: no hay navegación de interfaz. |
| UI | Interfaz de consola en `main.py`, `backtest.py` y `demo_live.py`; no hay interfaz gráfica. El entrypoint `demo_live.py` no llega a cargar actualmente. |
| contenido | No hay subsistema de contenido. El bot persiste señales y resultados en `signals_log.json` y `backtest_results.json`. |
| utilidades | `executor.py` construye swaps locales, simula con `eth_call` y registra señales; `binance_web3_api.py` implementa cliente autenticado para endpoints RWA. |
| configuración | `config.py`, `.env.example` y `requirements.txt`. |

## 6. Repository Health

| Elemento | Estado |
|----------|--------|
| check | ✅ Suite completa: 47/47 pruebas OK. || build | ❌ No se encontró configuración ni comando de build. |
| Arquitectura | ⚠ No contrastable con Plan Maestro/ADR; hay discrepancias entre flujos documentados y código. |
| Documentación | ⚠ Existen documentos, pero las afirmaciones sobre LIVE y el alcance del MVP se contradicen. |
| ADR | ⚠ No se encontraron ADR. |
| Bloqueadores conocidos | Plan Maestro y ADR ausentes; demo LIVE falla al importar `build_approve_transaction`; faltan en el cliente Binance los métodos de Trading API usados por el flujo. |

## 7. Deuda técnica conocida

Limitaciones declaradas en [README.md](README.md):

- El MVP no cubre descuentos/redeem, cuyo flujo requiere KYC y liquidación off-chain.
- El histórico on-chain del backtest es sintético, no histórico real de blockchain.
- El flujo principal no firma ni ejecuta transacciones reales.
- Las alertas se limitan a logs/JSON.
- No hay interfaz visual.
- Ondo figura como integración opcional, no como validación cruzada completa.

Además, el código identifica un defecto reproducible en la demo: `demo_live.py` no puede importarse porque `executor.py` no define `build_approve_transaction` (ni las otras funciones LIVE que importa). `validate_dry_run.py` también importa funciones del executor que no están definidas.

## 8. Desviaciones existentes

- [README.md](README.md) declara que no hay firma ni ejecución real y presenta `main.py` como flujo de simulación. En cambio, [BINANCE_WEB3_INTEGRATION.md](BINANCE_WEB3_INTEGRATION.md) y [DEMO_CHECKLIST.md](DEMO_CHECKLIST.md) describen y dan por disponible un flujo LIVE. `demo_live.py` contiene ese flujo, pero falla al cargar por símbolos ausentes en `executor.py`.
- La integración y el informe de validación describen métodos como `get_aggregated_quote`, `build_swap_transaction` de Trading API, `build_approve_transaction`, `sign_transaction`, `broadcast_signed_transaction` y `verify_transaction`. El `BinanceWeb3API` actual solo define endpoints RWA (precio, catálogo, búsqueda y mercado subyacente); `executor.py` solo define construcción local, simulación y registro. Los métodos de Trading y ejecución documentados no están implementados en esos módulos.
- [VALIDATION_REPORT.md](VALIDATION_REPORT.md) afirma que la integración DRY E2E está lista y que LIVE está bloqueado solo por fondos/KYT; la importación fallida del demo demuestra que el flujo descrito no es ejecutable en el estado actual, independientemente de esos requisitos externos.
- El badge de [README.md](README.md) indica 21 pruebas, mientras [VALIDATION_REPORT.md](VALIDATION_REPORT.md) indica 26 y la ejecución actual confirma 26.

## 9. Próxima fase

**No determinable; auditoría detenida.** No se encontró el Plan Maestro que define la siguiente fase y se detectaron contradicciones documentales con el código. No se infiere ni propone una fase.

- **Objetivo:** no consta en una fuente de planificación disponible.
- **Dependencias:** no enumerables ni verificables sin el Plan Maestro. Por tanto, no se puede confirmar que estén implementadas.
- **Archivos previstos:** no definidos en la documentación disponible.
- **Criterios de aceptación:** no definidos en la documentación disponible.
- **Riesgos conocidos:** demo LIVE y validación DRY hacen referencia a símbolos ausentes; el cliente Binance carece de los métodos Trading documentados; alcance de ejecución en README e integración no coincide.

No es posible verificar que no haya decisiones arquitectónicas pendientes: no existen ADR localizados. La documentación sí contiene contradicciones comprobadas, y sin el Plan Maestro no se puede identificar qué componentes previos exige la próxima fase. En consecuencia, no se declara que sus dependencias estén implementadas ni que la fase esté aprobada.

---

## 10. Estado tras cierre MVP (Commit 8)

**Suite de tests:** 47/47 OK (`python -m unittest discover -v`)

### Commits 0–8

| # | Hash | Mensaje |
|---|------|---------|
| 0 | 23b8bd4 | feat: Add executor module and main bot loop for automated trading |
| 0 | 585b6e5 | feat: Add Decimal import to main.py and enhance test coverage for executor module |
| 0 | 37205c5 | feat: Add backtesting functionality and enhance executor diagnostics for transaction simulation |
| 0 | 912f602 | feat: Integrate Binance Web3 API for RWA data fetching and enhance price calculation logic |
| 1 | 55f4902 | chore: add hackathon docs, demo scripts and gitignore rules |
| 2 | bf43501 | feat(executor): add live transaction helpers (build, sign, broadcast, verify) |
| 3 | a03bcb8 | feat(binance_web3_api): add trading, transaction and wallet endpoints |
| 3b | ab486bd | refactor(validate_dry_run): guard module-level execution behind __main__ |
| 4 | 25c5601 | fix(data_fetcher): propagate ondo_timestamp from fetch_ondo_price |
| 5 | 7c78683 | test(live_flow): add unit tests for executor LIVE helpers and BinanceWeb3API trading endpoints |
| 6 | 257d662 | feat(demo_live): enforce --max-live-tx limit with preflight |
| 7 | 77f6cd8 | chore(env): document live wallet and session limit placeholders |
| 8 | *(este commit)* | docs: sync README, STATUS_MATRIX and integration docs with MVP scope |

### Pendientes reales tras cierre MVP

| Pendiente | Tipo | Descripción |
|---|---|---|
| (a) Video demo | Entregable | Grabar demo DRY + intro arquitectura (~5 min) |
| (b) git push | Operativo | `git push origin main` tras aprobación explícita |
| (c) Deuda técnica: `ondo_timestamp` duplicado | Código | `data_fetcher.py` asigna `ondo_timestamp` dos veces (líneas ~532 y ~536); la segunda es redundante pero inofensiva. Limpiar en Commit 9. |
| (d) Badge README | Cosmético | Verificar que el badge 47-passing sea visible en GitHub tras push. |
| (e) Revocar approve post-demo | Operativo | Tras demo LIVE, revocar allowance (`amount_wei=0`) al router. |
