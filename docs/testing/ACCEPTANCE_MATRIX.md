# Matriz de aceptación — AILEN

> Criterios verificables para evitar marcar hitos como completos por intuición.

## 1. Foundation (`0.1.x`)

| Área | Criterio |
|---|---|
| CLI | `ailen --help` devuelve ayuda y exit code 0 |
| Import | `import ailen` no inicia servicios ni accede a hardware |
| Config | config válida carga; config inválida falla con mensaje legible |
| Secretos | no hay claves/tokens/contraseñas reales en repo |
| Runtime | estado puede serializarse sin secretos |
| Hardware | diagnóstico tolera ausencia de cámara/audio/GPU |
| SQLite | DB nueva se crea mediante migración, no mediante SQL improvisado en handlers |
| Web | servidor local inicia con datos fake/sintéticos |
| Tests | suite foundation ejecuta sin Internet, cámara, micrófono ni GPU |
| Docs | estructura implementada coincide con documentación/ADR |

## 2. Core/state

| Área | Criterio |
|---|---|
| Estado | transiciones inválidas son rechazadas o manejadas explícitamente |
| Bloqueos | una operación de red/inferencia no congela Face/Web |
| Eventos | eventos tienen timestamp/tipo/source y correlation id cuando corresponde |
| Social | saludo respeta cooldown/debounce |
| Público | `PUBLIC/SHOP` no recupera memoria privada fuera de allowlist |
| Degradación | falla de un adapter no derriba todo el proceso salvo error fatal documentado |

## 3. Memoria

| Área | Criterio |
|---|---|
| Sesiones | crear/cerrar sesión persiste correctamente |
| Mensajes | roles/timestamps se conservan |
| Recuerdos | memoria explícita puede buscarse y eliminarse |
| FTS | si FTS5 no está disponible, existe fallback o error documentado |
| Migraciones | DB antigua de fixture actualiza sin pérdida inesperada |
| Privacidad | API cloud recibe sólo memoria seleccionada, nunca query global automática |
| Logs | conversación completa no aparece en logs operativos por defecto |

## 4. AI Router

| Caso | Resultado esperado |
|---|---|
| volumen/play/pause | tool/regla local, sin LLM |
| cloud prohibido | cloud nunca se selecciona |
| presupuesto agotado | cloud bloqueado y fallback/limitación legible |
| Internet caído | cloud omitido sin crash |
| LAN Brain caído | fallback local/cloud según política |
| privacidad alta | backend que viole política no es elegible |
| timeout | fallback limitado; no loop infinito |
| métrica | backend/motivo/latencia/usage quedan registrados sin secretos |

## 5. Face

| Área | Criterio |
|---|---|
| Idle | animación estable durante prueba prolongada |
| CPU | FPS limitado y consumo idle medido |
| Gaze | coordenadas normalizadas mueven pupilas sin acceso directo a cámara |
| States | cambios `IDLE/LISTENING/THINKING/TALKING/SLEEP` visibles |
| Speech | boca puede reaccionar a nivel/temporización sin análisis pesado |
| Falla | ausencia de display puede activar perfil/headless adecuado |

## 6. Vision

| Área | Criterio |
|---|---|
| Cámara | enumera/abre dispositivo configurado |
| Presencia | no emite eventos infinitos por cada frame |
| Debounce | presencia debe estabilizarse antes del saludo |
| Gaze | entrega coordenadas normalizadas |
| Privacidad | no almacena frames automáticamente |
| Rendimiento | FPS/config ajustable y benchmark registrado |

## 7. Audio/STT/TTS

| Área | Criterio |
|---|---|
| Audio | enumera input/output y permite test explícito |
| Grabación | captura sin bloquear Core |
| STT | frase española de prueba se transcribe con latencia registrada |
| TTS | primera salida audible con latencia registrada |
| Música | voz puede hacer ducking de música si está habilitado |
| Feedback | TTS no debe provocar loops evidentes de escucha en flujo normal |
| Falla | pérdida de dispositivo produce error recuperable |

## 8. Web Admin

| Área | Criterio |
|---|---|
| Mobile | usable desde pantalla móvil sin scroll horizontal obligatorio |
| Desktop | usable desde PC/monitor |
| Auth | contraseña no se guarda en texto plano |
| Cookies | flags de seguridad apropiados según despliegue |
| CSRF | protegido cuando corresponda al método elegido |
| Lockout | intentos repetidos limitados |
| Status | dashboard no lee SQLite/config cruda desde template/handler |
| Secretos | API keys nunca se reenvían completas al browser |
| LAN | bind/exposición configurables; Internet público deshabilitado por defecto |

## 9. Tools

| Área | Criterio |
|---|---|
| Schema | argumentos validados |
| Permiso | tool bloqueada en modo no autorizado |
| Timeout | I/O externo tiene timeout |
| Auditoría | éxito/fallo registrado sin datos sensibles excesivos |
| Shell | no existe tool de shell general |
| Error | tool fallida devuelve resultado estructurado, no traceback al LLM/cliente |

## 10. Appliance

| Área | Criterio |
|---|---|
| Boot | Debian minimal llega a AILEN automáticamente |
| Crash | proceso se recupera según política systemd |
| Display | Face inicia sin escritorio pesado |
| Datos | config/memoria viven fuera de release |
| Logs | rotación definida |
| Energía | suspensión/blanking adecuados al modo appliance |
| Mantenimiento | existe ruta documentada de acceso/diagnóstico |

## 11. Updater

| Área | Criterio |
|---|---|
| Hash/firma | release inválida no se activa |
| Aislamiento | nueva versión instala en directorio separado |
| Estado seguro | activación no corta operación sensible sin política |
| Health | versión nueva debe reportar estado saludable |
| Rollback | fallo post-activación restaura versión anterior |
| Persistencia | memoria/config no se borran ni reemplazan |
| Canal | stable/beta/nightly obedecen configuración |

## 12. Banghó prototype gate

Antes de desarmar físicamente la Banghó debe existir evidencia de:

- [ ] boot/autostart estable;
- [ ] Face estable;
- [ ] cámara/presencia estable;
- [ ] STT usable;
- [ ] TTS usable;
- [ ] una interacción completa;
- [ ] SQLite persistente tras reboot;
- [ ] panel web accesible desde celular;
- [ ] Internet offline no mata el sistema;
- [ ] temperatura/CPU/RAM registradas;
- [ ] prueba prolongada sin crash grave.

## 13. SF20BA gates

### 8 GB

- [ ] arranca el mismo software con perfil apropiado;
- [ ] RAM idle/peak documentadas;
- [ ] temperatura estable;
- [ ] interacción cloud suficientemente rápida;
- [ ] LLM local sólo si benchmark lo justifica.

### 4 GB

- [ ] no swap-thrashing continuo;
- [ ] cloud-first estable;
- [ ] Face/audio/presencia simultáneos sin bloqueo evidente;
- [ ] degradación de funciones automática/documentada.

### 2 GB

Sólo declarar soporte si:

- [ ] Core/Face/audio/presencia caben con margen operativo;
- [ ] cloud/LAN funciona sin thrashing;
- [ ] jornada prolongada estable;
- [ ] modo sin LLM local funciona correctamente.

## 14. Piloto comercial gate

Antes de ofrecerlo a un comercio externo:

- [ ] setup reproducible;
- [ ] admin con credenciales propias;
- [ ] privacidad pública validada;
- [ ] saludos no molestos;
- [ ] costo cloud medido;
- [ ] actualización/rollback probados;
- [ ] backup/restauración probados;
- [ ] manual de recuperación básico;
- [ ] hardware físico seguro y ventilado;
- [ ] política clara sobre cámara/micrófono/datos.
