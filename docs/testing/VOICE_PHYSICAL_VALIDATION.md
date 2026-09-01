# Validación física de voz

Este harness compara VAD WebRTC y Vosk usando el input real configurado. El PCM
sólo existe en RAM durante cada muestra; no se escribe WAV ni audio. Se guardan
frases públicas del corpus y métricas bajo
`runtime/lab/voice_validation/`, ruta ignorada por Git.

## Inspección sin abrir micrófono

```bash
.venv/bin/ailen -c config/ailen.toml lab audio-devices --json
.venv/bin/ailen -c config/ailen.toml lab calibrate-voice \
  --capture-gains 0,6 --auto-gain-modes off \
  --vad-modes 2 --silence-timeouts 500 --distances-cm 75 --limit 2 \
  --list-cases
```

## Matriz VAD/STT

```bash
.venv/bin/ailen -c config/ailen.toml lab calibrate-voice \
  --distances-cm 30,75,100 \
  --processing-profiles raw,noise_only,full \
  --vad-modes 2,3 \
  --silence-timeouts 380,500,600
```

La matriz incluye frases cortas/largas, pausas internas, voz baja, sí/no,
volumen, humor y charla cotidiana. Cada muestra pide primero 2–3 s de silencio y
luego habla a la distancia indicada. Registra fuente pedida/efectiva, RMS y peak
raw/tras NS/tras gain-AGC-limitador, SNR, clipping, falsos triggers, WER/CER, confianza real,
banda, onset/offset, duración PCM, truncamiento y latencia STT. `s` omite una
muestra; `q` conserva un resumen parcial. La recomendación penaliza clipping,
ruido amplificado, falsos VAD y WER; nunca modifica la configuración y exige
confirmación humana.

Sin `--device`, el harness descubre y compara un conjunto acotado y sin
duplicados: default observable, fuentes físicas PipeWire y Easy Effects Source
si existen. Excluye monitores y virtuales ajenos. Antes de capturar guarda en
`route_snapshot` el ID/nombre/estado/volumen porcentual/dB observado y advierte
fuentes atenuadas sin modificarlas. Por ejemplo:

```bash
.venv/bin/ailen -c config/ailen.toml lab calibrate-voice \
  --capture-gains 0,6 --auto-gain-modes off,on \
  --processing-profiles raw,noise_only,full \
  --vad-modes 2 --silence-timeouts 500 --distances-cm 30,75,100 --limit 2
```

Una fuente concreta puede pedirse como `--device
pipewire:<node-name>`. El backend la pasa como target explícito a `pw-record`;
no captura silenciosamente el default. Fuentes virtuales atenuadas se advierten
pero no se corrigen. No comparar endpoints si no pueden recibir el mismo guion,
distancia y condiciones.

`--device pipewire` es deliberadamente distinto: usa el default nativo de
`pw-record`, no agrega `--target` y sigue funcionando si `pactl` no está
disponible. En ese caso el resultado informa `pipewire`, no inventa el nombre del
nodo. Durante el silencio el harness mide RMS raw y propone
`auto_gain_noise_gate_rms`; el AGC no incrementa ganancia por debajo de ese gate,
sostiene pausas breves y luego decae. La propuesta requiere guardado/confirmación
humana y no se aplica sola.

Cada muestra muestra primero la fase de silencio y avisa cuándo hablar. Las
distancias por defecto son 30, 75 y 100 cm y pueden cambiarse con
`--distances-cm`.
El JSON y la consola incluyen RMS y peaks raw/gained/processed, SNR por etapa,
clipping, ganancia aplicada, falsos triggers VAD y fuente efectiva. No contienen
PCM. La configuración activa permanece en 0 dB/AGC apagado hasta que el operador
revise y confirme una recomendación.

Los perfiles se comparan sin alterar la fuente: `raw` no aplica DSP,
`noise_only` aplica sólo NS y `full` aplica NS + gain/AGC + limitador. Si la
fuente pedida es Easy Effects, se etiqueta `external_reference` y AILEN no añade
otro AGC/preamp.

## Barge-in real

```bash
.venv/bin/ailen -c config/ailen.toml lab calibrate-voice --barge-in-only
```

Ejecuta tres ensayos guiados: temprano, medio y tardío. Usa audio, Vosk, TTS y
el coordinador reales. Deben observarse por separado:

- interrupción y latencia de `AudioOutput.stop()`;
- frames acumulados y transcript marcado como interrupción;
- cancelación lógica de la generación;
- fin del drenaje de una inferencia TTS no cancelable;
- thread de habla terminado.

La prueba no afirma AEC: actualmente sólo existe discriminación acotada de
leakage/VAD. Una prueba unitaria o la muerte de `aplay` no valida que la frase
humana haya llegado a STT.

## Política de micrófono para equipos reciclados

El objetivo de producción es usar el micrófono integrado/nativo de la placa de
cada notebook o PC reciclada. El backend ya puede abrir un endpoint ALSA/PipeWire
explícito, pero el provisionador R6 de audio todavía no lo elige ni lo persiste:
los perfiles Lab usan `default`. El onboarding de una unidad debe identificar el
endpoint físico, ejecutar la matriz y persistirlo sólo si la evidencia es
suficiente. Ser interno no equivale a estar calificado. USB Composite/Jieli, G600
y Easy Effects son fuentes opcionales de laboratorio o fallback, no dependencias
del producto.

## Resultado físico más reciente

La campaña `voice-20260901T084132Z-1cfb53` fue **inconclusa y no aprobó un
perfil**: sólo capturó cinco muestras, una frase y 75 cm. El USB Jieli obtuvo WER
1,0 en raw y 0,5 con procesamiento; tres configuraciones mostraron 6, 28 o 30
falsos triggers de silencio. Easy Effects obtuvo WER 0,5 en una única muestra.
Aunque el ranking eligió `noise_only`, su `samples=1` y `wer_avg=0.5` no alcanzan
para persistir source, gain, AGC, VAD ni gate. El resultado puede corresponder a
limitación del micrófono USB, routing/nivel o condiciones de prueba; debe repetirse
en el taller con los micrófonos nativos de las placas.

## Interpretación

No persistir umbrales hasta completar suficientes muestras comparables y revisar
cortes perceptibles. Todo resultado de ASRock debe etiquetarse como contendido
si el Trading Bot estaba activo; no se extrapola a 4/8 GB.

En la inspección más reciente del 2026-09-01, `default` resolvió a USB
Composite/Jieli y Easy Effects Source figuró separado; el G600 visto en una
inspección anterior ya no estaba presente. Easy Effects había sido observado a
42%/-22,87 dB. Esto explica el drift de endpoint, pero no determina cuál escucha
mejor. Gain/AGC/NS no reemplazan AEC.
