# Developer Experience Report — bStock Arbitrage Bot

## Executive Summary
Integramos la API de Binance Web3 RWA en 10 horas. La API funciona correctamente, pero la documentación tiene fricciones significativas que
documentamos a continuación con sugerencias concretas.

## 1. Onboarding Timeline
- Tiempo total desde la primera lectura hasta la primera llamada exitosa: 8 horas
- Pasos:
  1. Registro en el hackathon: 10 min
  2. Solicitud de API key en Dev Portal: 15 min
  3. Implementación de la API key: 20 min
  4. Primera llamada exitosa: 35 min después de implementar la key

## 2. Fricciones Encontradas (Específicas y Accionables)

### Fricción #1: Headers de autenticación no estándar
- **Qué pasó**: Asumí que los headers eran `X-MBX-APIKEY` (como en Binance Spot).
  La API Web3 usa `X-OC-APIKEY`, `X-OC-TIMESTAMP`, `X-OC-SIGN`.
- **Impacto**: 35 minutos perdidos depurando `40102 Invalid signature`.
- **Sugerencia**: Añadir un ejemplo copy-paste de autenticación en Python en la
  página de Authentication.

### Fricción #2: El prefijo `/build` en el requestPath firmado
 /build, 
- **Qué pasó**: La firma HMAC incluye el requestPath. La documentación enfatiza el prefijo `/build`, pero su importancia no es evidente hasta que se comete el error. Un ejemplo de firma completa desde el principio habría ahorrado tiempo. Sin él, `40102 Invalid signature`.
- **Impacto**: 10 minutos perdidos.
- **Sugerencia**: Documentar el prefijo `/build` en negrita en la sección de
  autenticación, con un ejemplo de firma completa.

### Fricción #3: Inconsistencia entre nombres de parámetros
- **Qué pasó**: `chainId` vs `binanceChainId`. La documentación de autenticación usa `chainId` en el ejemplo de firma. Sin embargo, la API real espera `binanceChainId`; `tokenContractAddresses` (plural) para `/price` vs `tokenContractAddress` (singular) para `/underlying-market`.
- **Impacto**: 3 iteraciones de prueba-error con la API real.
- **Sugerencia**: Unificar los nombres de parámetros entre endpoints.

### Fricción #4: Estructura de respuesta anidada no documentada
- **Qué pasó**: `search` devuelve empresas con `ticker` y array `assets[]` donde `platformId=bstock` contiene la dirección. La documentación no muestra esta estructura.
- **Impacto**: 10 minutos depurando por qué el parser no encontraba la dirección.
- **Sugerencia**: Publicar ejemplos de respuesta completos para cada endpoint.

### Fricción #5: Códigos de error incompletos
- **Qué pasó**: Al omitir `binanceChainId`, la API devolvió `40001 Parameter binanceChainId is required`. La tabla de errores documenta el código `40001` con un formato genérico (`Parameter [field] error: <reason>`) y menciona `binanceChainId` vacío como disparador, pero no incluye el texto literal del mensaje, lo que dificulta la búsqueda inversa (del mensaje al código) durante la integración.
- **Sugerencia**: Aclarar explícitamente que el `msg` es dinámico y debe parsearse con el patrón Parameter `<field>` error: `<reason>`.

## 3. API Experience

### Lo que funcionó bien
- Autenticación robusta una vez configurada correctamente.
- `tokenPrice` y `referencePrice` devueltos en una sola llamada.
- `statusInfo.openState` es clave para saber si el mercado subyacente está abierto.
- Rate limiting razonable (no alcanzamos límites en pruebas).

### Lo que podría mejorar
- No hay endpoint público de estado del sistema.
- No hay endpoint de histórico de precios para backtests reales.
- Los timeouts por defecto no están documentados.

## 4. AI Stack Feedback

Usé Chat.DeepSeek, Antigravity y VS Code para:
- Scaffolding del cliente HTTP y tests.
- Iteración sobre errores de la API una vez obtenidos.

**Fortalezas de la IA**:
- Generó la estructura general del cliente correctamente.
- Iteró rápido sobre los errores que le proporcioné.

**Debilidades de la IA**:
- Asumió headers de Binance Spot (`X-MBX-APIKEY`) en lugar de Web3 (`X-OC-*`).
- Usó hex encoding en lugar de Base64 para la firma.
- Omitió el prefijo `/build` en el requestPath firmado.

**Lección**: La IA necesita ejemplos concretos de la documentación oficial para no alucinar. Proporcionar la URL de autenticación real fue lo que desbloqueó la integración.

## 5. Tokenized Stocks Specifics

- El spread `tokenPrice / referencePrice - 1` es la métrica clave.
- Cuando es 0%, el mercado está eficientemente arbitrado.
- Los fines de semana el subyacente se congela, pero el token sigue cotizando.
  Ahí es donde aparecen las oportunidades (caso 4Stock con prima del 10x).
- `statusInfo.openState=False` permite distinguir spreads reales de artefactos.
- Un endpoint de "histórico de spreads" sería muy valioso para backtests.

## 6. Sugerencias Priorizadas

| Prioridad | Sugerencia | Impacto |
|---|---|---|
| Alta | Ejemplos copy-paste de autenticación en Python y JS | Reduce onboarding 2h → 15min |
| Alta | Documentar `/build` en el requestPath firmado | Elimina `40102` más común |
| Media | Unificar nombres de parámetros | Reduce iteraciones prueba-error |
| Media | Ejemplos de respuesta completa para cada endpoint | Facilita el parsing |
| Baja | Endpoint público de estado del sistema | Mejora monitoreo |
| Baja | Endpoint de histórico de precios | Habilita backtests reales |

## 7. Conclusión

La API de Binance Web3 RWA es funcional y bien diseñada. Una vez superadas las fricciones de autenticación (1-2 horas), el desarrollo fluye rápidamente. Con las mejoras sugeridas, el onboarding podría reducirse a 30 minutos.
