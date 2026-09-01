# Calificación de LLM locales por hardware

AILEN soporta Ollama y llama.cpp detrás del mismo contrato de inferencia, pero
una ficha que entra en RAM no equivale a un modelo apto para conversación. La
calificación es por artefacto exacto y por clase de hardware objetivo; ASRock es
laboratorio y no certifica equipos reciclados de 4 u 8 GB.

## Estados

- `candidate`: metadata plausible o artefacto identificado; faltan una o más
  mediciones del stack completo.
- `qualified`: fuente, licencia, formato, digest, chat template y benchmark en
  hardware objetivo fueron verificados.
- `rejected`: existe evidencia suficiente para no ofrecer ese artefacto; debe
  conservarse el motivo.

`downloadable=true` sólo significa que URL HTTPS, tamaño y SHA-256 son exactos.
No promueve el modelo a `qualified`.

## Evidencia obligatoria

Cada manifiesto debe registrar:

1. URL y referencia de origen exactas;
2. licencia revisada;
3. formato y cuantización;
4. tamaño y SHA-256 o LFS OID verificable;
5. runtime y chat template;
6. dispositivo de ejecución y offload realmente usados;
7. contexto efectivo;
8. hardware identificado, RAM total y RSS/VRAM pico del stack cuando estén
   disponibles;
9. TTFA, tokens/s y calidad sobre un prompt set versionado;
10. fecha y notas de la medición.

Crear una plantilla no descarga pesos:

```bash
.venv/bin/ailen models qualification-template MODEL_ID \
  --output runtime/lab/model_qualification/MODEL_ID.json
```

Validarla de forma fail-closed:

```bash
.venv/bin/ailen models qualification-validate \
  runtime/lab/model_qualification/MODEL_ID.json
```

Un estado `qualified` incompleto es rechazado. Los artefactos y reportes Lab no
se empaquetan en el wheel.

La decisión de instalación se inspecciona sin descargar:

```bash
.venv/bin/ailen models provision-plan --topology hybrid --json
```

El comando combina el reporte real con registros versionados de
`runtime/lab/model_qualification/hardware/`. La clave de esos registros es una
clase de capacidades no identificante (banda RAM, CPU/AVX2, arquitectura y VRAM),
no el nombre comercial del host. Un override `--model-override` es sólo para
laboratorio: se rechaza si falta calificación target-specific o si no entra.

El índice de decisión es, como mínimo,
`(hardware_class, model_id, runtime)`. Cada runtime se mide por separado: que un
GGUF pueda abrirse con Ollama y llama.cpp no permite trasladar resultados entre
ellos. Si ambos están calificados, el planner compara calidad, TTFA, tokens/s y
RSS/VRAM observados; si sólo uno lo está, ése es el único elegible aunque la
recomendación genérica prefiera otro. Los registros anteriores que no declaran
dispositivo/offload se leen como CPU con `gpu_layers=0`; nunca se infiere CUDA.
El offload parcial no forma parte del contrato actual.

## Perfiles de prueba, no promesas

- `recycled-4gb-local-candidate`: reserva sistema/voz y evalúa un GGUF pequeño
  con contexto acotado.
- `recycled-8gb-hybrid`: permite elegir mayor `quality_rank` si la evidencia y
  el margen real lo permiten; conserva un candidato menor como fallback.
- `lan-satellite`: no carga LLM local y delega a un Brain configurado.
- `gpu-lan-brain`: usa hardware capaz como nodo LAN, sin convertirlo en mínimo
  comercial.
- `external-only`: instalación explícita con local estrictamente deshabilitado.

El planner filtra primero seguridad, plataforma, cuantización, contexto y
memoria. Dentro de ese envelope ordena por estado de calificación, evidencia de
benchmark y `quality_rank`; el tamaño es desempate, no la política principal.
No realiza model hopping por turno. Para 16/32/64+ GB no hay un techo universal
de 6 GB: se reserva el mayor valor entre el piso de cada banda y 15% de la RAM
total, y se evalúa el resto disponible junto con VRAM dedicada real. La memoria
compartida de una iGPU no se cuenta dos veces.

El runtime propuesto también es parte de la activación. Una selección automática
sólo puede exponer el modelo si el descriptor que llega al factory está
`qualified`; `ai.local.runtime=llama_cpp|ollama` impide ejecutar el mismo ID en
un runtime distinto. `auto` se conserva para un override Lab explícito y no
autoriza a transferir calificaciones.

Después de instalar y verificar el artefacto exacto, la activación es una acción
separada y consentida:

```bash
.venv/bin/ailen -c config/ailen.toml lab prepare-ai \
  --qualification-dir runtime/lab/model_qualification/hardware \
  --activate-selection
```

El comando no descarga sin `--yes`. `--activate-selection` vuelve a verificar el
SHA-256 y persiste atómicamente, con modo `0600`, la clase de hardware, runtime,
modelo, contexto y dispositivo/offload seleccionados en
`<node.data_dir>/provisioning/local-ai-selection.json`. Una selección no se
activa si el modelo sigue `candidate`, el artefacto falta o el hash no coincide.
El runtime sólo la lee cuando `ai.local.enabled=true` y `ai.local.model` está
vacío; un modelo explícito sigue siendo override de laboratorio. Cambiar de clase
de hardware invalida el registro y obliga a provisionar otra vez.

## Estado actual

Los Qwen 3.5 0.8B Q4_0/Q8_0 poseen artefactos descargables identificados, pero
siguen `candidate` hasta medir calidad, TTFA, throughput y RSS en el equipo
objetivo con Vosk, Piper, SQLite y rostro activos. Las bandas 1–1.7B Q4 y 3–4B
Q4 son hipótesis de calificación: no tienen hashes inventados, no se descargan y
no se anuncian como soportadas.

## Incorporar un modelo futuro

Qwen, Llama, DeepSeek, Kimi, MiniMax u otra familia sigue exactamente el mismo
proceso; la marca no otorga prioridad. Para añadirlo:

1. identificar un artefacto GGUF exacto y revisar licencia/distribución;
2. registrar URL HTTPS, tamaño, SHA-256/LFS OID, cuantización, runtime soportado,
   contexto efectivo y chat template, dejándolo `candidate`;
3. ejecutar el prompt set versionado en cada clase objetivo con el stack completo
   y guardar RSS pico, TTFA, tokens/s, calidad y fallos;
4. revisar evidencia y emitir un registro `qualified` o `rejected` para esa
   clase;
5. volver a generar `ProvisioningPlan`. Sólo entonces podrá aparecer una acción
   de descarga/activación sujeta a consentimiento.

No se copian IDs, hashes ni requisitos desde APIs remotas a este catálogo: un
modelo servido por API y un GGUF local son artefactos distintos.
