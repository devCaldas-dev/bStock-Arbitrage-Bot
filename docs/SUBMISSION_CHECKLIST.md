# Submission Checklist — BNB Hack: Tokenized Stocks Edition

## Repositorio

- [x] Código en GitHub: https://github.com/ej-pro-i/arbritage-bot
- [x] README completo con arquitectura, decisiones técnicas y limitaciones
- [x] 47/47 tests pasando (`python -m unittest discover -v`)
- [x] `.env` y artefactos ignorados; `.env.example` con placeholders
- [x] Sin claves privadas ni API secrets en el historial

## Documentación

- [x] `README.md` — problema, solución, arquitectura, comandos
- [x] `docs/SUMMARY.md` — recorrido de desarrollo (histórico)
- [x] `docs/DEVELOPER_EXPERIENCE_REPORT.md` — informe DevEx con 5 fricciones y sugerencias priorizadas
- [x] `STATUS_MATRIX.md` — estado del proyecto y pendientes reales
- [x] `BINANCE_WEB3_INTEGRATION.md` — integración RWA
- [x] `VALIDATION_REPORT.md` — resultados DRY
- [x] `DEMO_CHECKLIST.md` — pasos del demo

## Criterios del hackathon

- [x] Uso de API oficial Binance Web3 RWA (fuente primaria)
- [x] Módulos de hackathon implementados: RWA, Trading, Transaction, Wallet
- [x] Reporte de Developer Experience (25% del puntaje)
- [ ] Video demo (~5 min) — **PENDIENTE**
- [ ] URL del video adjunta en submission — **PENDIENTE**

## Alcance declarado (honestidad técnica)

- Flujo LIVE (`demo_live.py --live`) implementado, cubierto por tests con mocks, no ejecutado con fondos reales
- Backtest on-chain simulado (±3%), documentado como limitación
- Arbitraje de descuento fuera de alcance (requiere KYC/redención off-chain)

## Pendientes antes de submit

- [ ] Grabar video demo (DRY + arquitectura + honestidad de alcance)
- [ ] Subir video a plataforma (YouTube/Loom)
- [ ] Añadir URL del video al README en la línea `Ver video demo`
- [ ] Confirmar submission en el portal del hackathon
