# Documento de Estudio: Desarrollo de un Bot de Arbitraje para Acciones Tokenizadas en BNB Chain

**Subtítulo:** Análisis del proceso de diseño, implementación y depuración de un bot de arbitraje para bStocks durante el hackathon "BNB Hack: Edición de Acciones Tokenizadas", incluyendo la evolución técnica desde una arquitectura basada en Web3 directo hasta la integración con la API oficial de Binance Web3.

---

## Resumen Ejecutivo

La conversación aborda el desarrollo de un bot de arbitraje para acciones tokenizadas (bStocks) en BNB Chain durante el hackathon "BNB Hack: Edición de Acciones Tokenizadas". El proyecto evoluciona desde una idea inicial (detectar ineficiencias de precio entre bStocks en DEX y acciones reales subyacentes) hasta un MVP funcional con seis módulos: `data_fetcher`, `strategy`, `executor`, `main`, `backtest` y `binance_web3_api`.

El razonamiento atraviesa varias fases: definición del problema, elección de fuentes de datos, construcción incremental de módulos, depuración de errores reales contra la blockchain, y una corrección crítica final al descubrir que el bot no usaba la API oficial del hackathon. La integración con la API de Binance Web3 RWA se logra tras cinco iteraciones de errores de autenticación y parámetros. El estado final es un bot funcional con 26 tests pasando, documentación completa, y pendiente únicamente de video demo e informe de experiencia de desarrollador para su envío.

---

## Conceptos Principales

**bStocks (Acciones Tokenizadas):** Tokens que representan acciones reales de empresas cotizadas, operando 24/7 en BNB Chain. Ejemplos mencionados: TSLAB (Tesla, Backed Finance), TSLAon (Tesla, Ondo Finance).

**Arbitraje de prima positiva:** Mecanismo que consiste en acuñar bStock con USDC al precio del subyacente y venderlo en el DEX cuando el precio on-chain supera al de la acción real. Es el único automatizable según la conversación.

**Arbitraje de descuento:** Mecanismo inverso (comprar bStock barato en DEX y redimirlo por USDC). Descartado del MVP por requerir KYC y liquidación off-chain con el emisor.

**Spread o prima:** Diferencia porcentual entre el precio on-chain del bStock y el precio de la acción subyacente. Fórmula: `(onchain_price / underlying_price - 1) * 100`.

**PancakeSwap V2 vs V3:** El bot inicialmente usó V2, pero se descubrió que el pool de TSLAB en V2 tenía solo ~$5,000 de liquidez, produciendo un precio distorsionado ($382). V3 tiene ~$427,000 de liquidez y precio alineado con el mercado (~$364).

**sharesMultiplier / multiplier:** Factor que indica cuántas acciones representa un token. Crítico para calcular el precio por acción: `reference_price = token_price / multiplier`.

**API de Binance Web3 RWA:** API oficial del hackathon que devuelve `tokenPrice` (precio on-chain) y `referencePrice` (precio de la acción subyacente) en una sola llamada. Requiere autenticación con headers `X-OC-APIKEY`, `X-OC-TIMESTAMP` (ISO 8601) y `X-OC-SIGN` (Base64).

**STF (Safe Transfer From):** Error de simulación `eth_call` que indica que la dirección no tiene saldo del token o no ha aprobado el router. Se interpreta como comportamiento esperado en simulación.

---

## Evolución del Razonamiento

**Punto de partida:** La conversación inicia con una pregunta sobre la viabilidad de participar en el hackathon y qué construir en menos de 17 días. Se propone un bot de arbitraje para "4Stock" tras descartar otras ideas (agregador de swaps, creador de canastas).

**Fase 1 — Construcción del primer módulo:** Se diseña `data_fetcher.py` con dos fuentes: API de Ondo Finance (para precios) y API pública de Binance Web3 (para catálogo). Se descubre que el endpoint de Binance **no devuelve precios** sino un catálogo de 1,925 activos con metadatos (contrato, multiplicador).

**Fase 2 — Migración a Web3:** Se decide ir "directo a Web3" para eliminar la dependencia de la API key de Ondo. Se construye `web3_price_fetcher.py` que lee precios desde PancakeSwap V2.

**Fase 3 — Descubrimiento del problema de liquidez:** El bot obtiene un precio de $382 para TSLAB desde el pool V2, pero se detecta que ese pool tiene solo ~$5,000 de liquidez. Se migra a PancakeSwap V3, con pool de ~$427,000 de liquidez y precio alineado (~$364).

**Fase 4 — Motor de estrategia:** Se construye `strategy.py` con cálculo de costos (gas + fee + slippage), umbral de rentabilidad (1.5%), y lógica asimétrica que distingue entre prima positiva (BUY) y descuento (HOLD por no automatizable).

**Fase 5 — Ejecución y simulación:** Se construye `executor.py` que genera calldata de `exactInputSingle` V3, simula con `eth_call`, y diagnostica el error STF. Se construye `main.py` con loop autónomo.

**Fase 6 — Backtest:** Se crea `backtest.py` que simula 7 días de operación con precios históricos reales del subyacente y precios on-chain simulados con variación de ±3%.

**Fase 7 — Implementación crítica:** Hasta el momento el bot **no usa ningún módulo de la API oficial del hackathon**. Se integra la API de Binance Web3 RWA como fuente primaria, pasando por cinco iteraciones de errores:
1. Headers incorrectos (`X-MBX-APIKEY` → `X-OC-APIKEY`)
2. Firma en formato incorrecto (hex → Base64)
3. Prefijo `/build` omitido en el requestPath
4. Parámetro `chainId` → `binanceChainId`
5. `contractAddress` → `tokenContractAddresses` (plural para `/price`, singular para `/underlying-market`)

**Estado final:** Bot funcional con la API oficial como fuente primaria, fallback a PancakeSwap V3 + yfinance, 26 tests pasando, documentación completa. Pendiente: video demo e informe de experiencia de desarrollador.

---

## Argumentos Presentados

**Argumento a favor del arbitraje de prima positiva como caso de uso:**
El hackathon menciona el caso de 4Stock (BNC4) donde un trader ganó $230,000 aprovechando una prima del 10x. Esto demuestra que existen ineficiencias reales cuando el mercado subyacente está cerrado pero el bStock sigue cotizando 24/7.

**Argumento sobre la asimetría del arbitraje:**
El arbitraje de prima positiva (mint & sell) es automatizable porque se puede acuñar bStock con USDC al precio del emisor. El arbitraje de descuento requiere redención off-chain con KYC, por lo que se excluye del MVP.

**Argumento sobre la validación de liquidez:**
Un pool con $5,000 de liquidez produce precios distorsionados que parecen oportunidades de arbitraje pero no son ejecutables. Se implementa un umbral mínimo de $50,000 USD para rechazar pools ilíquidos.

**Argumento sobre el uso de la API oficial:**
El hackathon evalúa con 30% de peso la "Implementación técnica (módulos usados)" y 25% el "Informe de experiencia de desarrollador". Sin usar la API oficial, el puntaje se reduce drásticamente y no se es elegible para premios especiales.

---

## Alternativas Consideradas

**Ondo Finance como fuente de precios:**
Considerada inicialmente como fuente primaria. Descartada por requerir API key que puede tardar en aprobarse. Se mantiene como fallback opcional.

**yfinance (Yahoo Finance) como fuente de subyacente:**
Aceptada como fuente primaria temporal. Tras la integración de la API RWA, se degrada a fallback. Se verifica que `referencePrice` de Binance coincide con Yahoo Finance dentro de 0.37%.

**PancakeSwap V2 vs V3:**
V2 descartada por baja liquidez ($5K). V3 aceptada por mayor liquidez ($427K) y precio alineado con el mercado.

**Backtest con precios on-chain históricos reales:**
Considerada pero descartada por no haber fuente accesible. Se opta por simular precios on-chain con variación acotada de ±3%, documentando explícitamente esta limitación.

**Arbitraje de descuento:**
Descartado del MVP por requerir KYC y liquidación off-chain. Se documenta como limitación y se marca como HOLD en la lógica de estrategia.

**Múltiples DEX (V2 + V3 + Uniswap):**
Considerado pero no implementado. Se prioriza V3 de PancakeSwap por liquidez concentrada.

**Notifier de Telegram:**
Considerado como mejora visual para el video. No implementado en el MVP.

---

## Evidencias y Fundamentos

| Argumento | Nivel de respaldo | Evidencia |
|---|---|---|
| El pool V2 de TSLAB tiene ~$5K de liquidez | Alto | Verificación en PancakeSwap (captura mostrada) |
| El pool V3 de TSLAB tiene ~$427K de liquidez | Alto | Respuesta de la API de PancakeSwap V3 |
| La API de Binance Web3 requiere headers `X-OC-*` | Alto | Documentación oficial + error real `40102` |
| El prefijo `/build` es obligatorio en la firma | Alto | Error real `40102 Invalid signature` |
| `binanceChainId` es el nombre correcto del parámetro | Alto | Error real `40001 Parameter binanceChainId is required` |
| `tokenContractAddresses` (plural) para `/price` | Alto | Error real `40001 Parameter tokenContractAddresses is required` |
| `referencePrice` coincide con Yahoo Finance | Alto | Verificación: $378.71 (Binance) vs $380.12 (Yahoo) |
| El error STF es esperado en simulación | Alto | Diagnóstico del bot + explicación técnica |
| El spread actual es 0% (mercado eficiente) | Alto | `tokenPrice=378.36`, `referencePrice=378.36` |
| El hackathon requiere usar módulos de la API | Alto | Página de recursos del hackathon |

---

## Hipótesis e Inferencias Identificadas

### Hipótesis

**Hipótesis 1:** El endpoint público de Binance Web3 devolvía precios además de metadatos.
- Formulada durante la construcción inicial de `data_fetcher.py`.
- Refutada al descubrir que devuelve un catálogo de 1,925 activos sin precios.

**Hipótesis 2:** El precio de $382 obtenido del pool V2 representaba una oportunidad de arbitraje real.
- Formulada al ver la diferencia con el precio de Yahoo Finance.
- Refutada al descubrir que el pool V2 tenía solo $5K de liquidez.

**Hipótesis 3:** El bot podría funcionar sin usar la API oficial del hackathon.
- Implícita en las primeras fases del desarrollo.
- Refutada al analizar los criterios de evaluación del hackathon.

### Inferencias

**Inferencia 1:** La coincidencia entre `tokenPrice` y `referencePrice` (ambos $378.36) indica que el mercado está eficientemente arbitrado en ese momento.

**Inferencia 2:** La diferencia de 0.37% entre Binance y Yahoo Finance se debe al delay de ~15 minutos de Yahoo Finance.

**Inferencia 3:** El error STF en simulación es esperado porque la dirección ficticia no tiene saldo de TSLAB ni aprobación del router.

**Inferencia 4:** La estructura anidada de la respuesta de `search` (empresa → assets[] → platformId=bstock) no estaba documentada, lo que causó fricción en el parsing.

---

## Elementos Especulativos Detectados

**Afirmación:** El agente inicial asumió que la API de Binance Web3 usaría headers `X-MBX-APIKEY` (estándar de Binance Spot).
- **Razón de escepticismo:** No había evidencia en la conversación de que esa fuera la convención correcta. Se corrigió tras el error real `40102`.

**Afirmación:** El backtest con precios on-chain simulados con ±3% demuestra capacidad de detección.
- **Razón de escepticismo:** Los spreads del backtest no están correlacionados con la realidad histórica. Se reconoce explícitamente como limitación metodológica.

**Afirmación:** El bot detectará oportunidades similares al caso 4Stock.
- **Razón de escepticismo:** No hay datos históricos on-chain para validar esta afirmación. Es una expectativa basada en la lógica del arbitraje, no en evidencia empírica.

---

## Observaciones Críticas Sustentadas

**Limitación 1: El backtest usa precios on-chain simulados.**
Evidencia: El propio agente documenta que "el precio on-chain del backtest es una SIMULACIÓN basada en la referencia actual y una variación de hasta ±3%; no es histórico real de blockchain."

**Limitación 2: El arbitraje de descuento no es automatizable.**
Evidencia: Requiere redención off-chain con KYC, como se documenta en el README y en la lógica de estrategia.

**Limitación 3: La simulación de transacciones revierte con STF.**
Evidencia: Las 5 simulaciones del test forzado devolvieron `success=false` con `revert_reason: "execution reverted: STF"`. Se documenta como comportamiento esperado.

**Contradicción identificada:** El agente afirmó inicialmente que el bot "estaba listo" cuando no usaba ninguna API del hackathon. El usuario corrigió esta percepción señalando la página de recursos.

**Supuesto implícito:** Se asumió que la dirección del SwapRouter V3 de PancakeSwap era `0x1b81D678ffb9C0263b24A97847620C99d213eB14`. Se verificó que existe (12,154 bytes de código) y que el selector `0x414bf389` es correcto.

**Sesgo identificado:** Optimismo inicial sobre la viabilidad del bot sin API oficial. Corregido tras el análisis de los criterios de evaluación.

---

## Conocimientos Reutilizables

**1. Validación de liquidez en DEX:**
Un pool con liquidez baja produce precios distorsionados que parecen oportunidades de arbitraje pero no son ejecutables. Siempre verificar la liquidez antes de confiar en un precio.

**2. Distinción entre precio de token y precio por acción:**
En tokens fraccionados, el precio on-chain puede ser por token, no por acción. Usar el multiplicador para normalizar antes de comparar.

**3. Uso de `Decimal` para precisión financiera:**
Nunca usar `float` para cálculos de precios o spreads. Usar `Decimal` con precisión suficiente para evitar errores de redondeo.

**4. Autenticación HMAC en APIs:**
La fórmula `Base64(HMAC-SHA256(timestamp + method + requestPath + body))` es común en APIs financieras. El requestPath debe incluir el prefijo completo (ej. `/build`).

**5. Diagnóstico de errores en simulación:**
Un error de revert en `eth_call` no es necesariamente un bug. Puede indicar falta de saldo, aprobación, o condiciones de mercado. Documentar el error con contexto.

**6. Cascada de fuentes de datos:**
Diseñar sistemas con fuente primaria + fallbacks mejora la robustez. Documentar claramente qué fuente se usa en cada momento.

**7. Honestidad técnica en documentación:**
Documentar limitaciones (backtest simulado, arbitraje de descuento no automatizable) suma credibilidad ante evaluadores.

**8. Verificación de APIs oficiales:**
Antes de asumir la estructura de una API, verificar contra la documentación real y hacer llamadas de prueba. Los errores reales son la mejor fuente de información.

---

## Prioridad de los Conocimientos

**Crítico:**
- La API de Binance Web3 RWA es la fuente primaria de precios.
- La autenticación requiere headers `X-OC-*` y firma Base64.
- El arbitraje de prima positiva es el único automatizable.
- La validación de liquidez es esencial para evitar falsas señales.

**Importante:**
- La asimetría mint vs redeem define el alcance del MVP.
- El error STF es esperado en simulación.
- El backtest usa precios on-chain simulados.
- Los tests cubren 26 casos.

**Complementario:**
- El caso 4Stock (prima 10x) motivó el proyecto.
- La diferencia entre Yahoo Finance y Binance es ~0.37%.
- El selector del router V3 es `0x414bf389`.

**Accesorio:**
- Los badges del README.
- La estructura de archivos del proyecto.
- Los comandos de ejecución.

---

## Preguntas Pendientes

1. ¿El video demo final mostrará la API oficial en acción o el mock con señal BUY forzada?
2. ¿El informe de experiencia de desarrollador será aceptado sin haber usado la API en producción real?
3. ¿El bot detectará oportunidades reales durante el período de evaluación del hackathon?
4. ¿La integración con la API RWA funcionará sin problemas durante la demostración final?
5. ¿El jurado valorará la honestidad sobre las limitaciones del backtest?

---

## Nivel Global de Confianza

**Alto.**

**Justificación:** La conversación contiene evidencia concreta y verificable de múltiples fuentes: outputs de terminal, respuestas reales de APIs, errores específicos con códigos, y verificaciones cruzadas entre fuentes de datos. Las afirmaciones técnicas están respaldadas por pruebas ejecutadas. Las limitaciones se documentan explícitamente. La incertidumbre restante se refiere a la evaluación del hackathon y al rendimiento del bot en condiciones reales de mercado, que están fuera del control del equipo.

---

## Resumen para Reanudar el Tema

El proyecto consiste en un bot de arbitraje para acciones tokenizadas (bStocks) en BNB Chain, desarrollado durante el hackathon "BNB Hack: Edición de Acciones Tokenizadas". El bot detecta primas positivas entre el precio on-chain de un bStock y el precio de la acción real subyacente.

**Ideas fundamentales:**

1. **Problema:** Los bStocks cotizan 24/7 pero las acciones reales solo en horario de mercado, creando ineficiencias como el caso 4Stock (prima 10x).

2. **Arquitectura:** Seis módulos (`binance_web3_api`, `data_fetcher`, `strategy`, `executor`, `main`, `backtest`) que cubren desde la obtención de datos hasta la simulación de transacciones.

3. **Fuente de datos primaria:** API oficial de Binance Web3 RWA, que devuelve `tokenPrice` (on-chain) y `referencePrice` (subyacente) en una sola llamada autenticada con headers `X-OC-*` y firma Base64.

4. **Fallbacks:** PancakeSwap V3 (Web3) y Yahoo Finance (yfinance) si la API falla.

5. **Lógica asimétrica:** Solo se automatiza el arbitraje de prima positiva (mint & sell). El descuento requiere KYC off-chain y se marca como HOLD.

6. **Validación de liquidez:** Se rechazan pools con menos de $50,000 USD para evitar precios distorsionados.

7. **Simulación:** Se construye calldata de `exactInputSingle` V3 y se simula con `eth_call`, capturando errores como STF (falta de saldo/aprobación) con diagnóstico detallado.

8. **Backtest:** 7 días simulados con 14 señales BUY y spread máximo de 8.24%, usando precios on-chain simulados con ±3% (limitación documentada).

9. **Estado actual:** 26 tests pasando, documentación completa, pendiente video demo e informe de experiencia de desarrollador para el envío.

10. **Aprendizaje clave:** Verificar siempre contra la API real antes de asumir estructuras. Los errores reales (40102, 40001) son la mejor fuente de información para corregir la integración.# Resumen de la charla técnica del proyecto.
