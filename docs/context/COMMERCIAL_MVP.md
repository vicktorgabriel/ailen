# MVP comercial — AILEN

> Define la primera versión que podría probarse con un comerciante local. No es una lista de todas las ideas futuras.

## 1. Propuesta de valor

Reutilizar hardware económico o reciclado para ofrecer un asistente físico visible y conversacional que pueda acompañar un comercio, taller u hogar sin requerir una PC moderna, una app móvil dedicada ni un operador técnico permanente.

## 2. Qué compra/recibe el cliente

Conceptualmente:

- unidad física con pantalla o monitor si corresponde;
- cámara, micrófono y parlante;
- AILEN instalado como appliance;
- rostro/personaje configurado;
- panel web responsive en LAN;
- información de su negocio cargada;
- IA configurada según perfil;
- actualización remota/automática mediante releases;
- procedimiento básico de soporte/recuperación.

## 3. Perfiles comerciales técnicos

### Cloud

Hardware objetivo: 2–4 GB cuando las pruebas lo validen.

- inferencia principal por API económica/rápida;
- herramientas y memoria locales;
- rostro/audio/presencia locales;
- costo mensual controlado;
- operación básica degradada si Internet falla.

### Hybrid

Hardware objetivo: 4–8 GB.

- LLM local pequeño para fallback/tareas apropiadas;
- cloud para velocidad/calidad cuando conviene;
- LAN Brain opcional;
- memoria e identidad locales.

### Local

Hardware moderno.

- LLM local como opción principal;
- cloud opcional;
- mayor privacidad/autonomía;
- mismas funciones y administración que las otras variantes.

El cliente no debería necesitar entender estos detalles salvo que quiera configuración avanzada.

## 4. Funciones del primer piloto comercial

Obligatorias:

- saludo automático configurable;
- detección de presencia básica;
- rostro 2D con atención/escucha/habla/sueño;
- conversación corta;
- preguntas frecuentes del negocio;
- información de horarios/servicios/pagos;
- búsqueda web controlada;
- música;
- notas/recordatorios simples;
- panel web autenticado;
- memoria local;
- costo/uso cloud visible;
- actualización y rollback;
- backup básico.

No obligatorias para piloto:

- reconocimiento facial;
- visión multimodal general;
- integración con POS/ERP;
- control físico de dispositivos;
- dashboard cloud remoto;
- robot móvil;
- avatar 3D.

## 5. Configuración por el comerciante

El panel debe hablar en términos de negocio, no de prompts.

Campos deseados:

```text
Mi negocio
- Nombre
- Descripción
- Horarios
- Servicios
- Formas de pago
- Preguntas frecuentes
- Qué cosas no debe responder

Comportamiento
- Saludar al entrar
- Tiempo/cooldown
- Tranquilo / Normal / Conversador
- Permitir humor
- Permitir conversación espontánea

IA
- Automático
- Presupuesto mensual
- Permitir cloud
- Permitir LAN Brain

Privacidad
- Modo público
- Guardar conversaciones sí/no
- Retención
```

## 6. Modelo de servicio futuro

Dos opciones compatibles:

### Clave API del cliente

Ventajas:

- infraestructura nuestra mínima;
- cliente paga consumo directamente.

Desventajas:

- setup más técnico;
- exposición/gestión de credenciales más compleja.

### Gateway administrado por nosotros

Ventajas:

- experiencia simple;
- posibilidad de IA incluida en una cuota;
- control de límites/proveedores/fallback.

Desventajas:

- requiere backend propio, disponibilidad, facturación y soporte.

No implementar gateway comercial propio antes de validar el piloto local.

## 7. Costos cloud

El sistema debe medir consumo real desde el primer backend cloud integrado.

Registrar por interacción:

- proveedor;
- modelo;
- tokens entrada/salida si se informan;
- costo estimado;
- latencia;
- motivo de routing.

Permitir:

- presupuesto diario;
- presupuesto mensual;
- bloqueo/fallback al superar límite;
- vista acumulada desde el panel.

No basar el precio comercial en estimaciones hasta tener datos de uso real en piloto.

## 8. Experiencia esperada en comercio

El asistente no debe llamar atención de forma molesta.

Ejemplo:

```text
persona entra
-> AILEN la detecta
-> la mira
-> espera estabilidad
-> "Buenas tardes."
-> permanece en silencio
```

Si la persona interactúa:

```text
cliente pregunta
-> escucha
-> resuelve FAQ/tool/AI
-> responde
-> vuelve a estado atento/idle
```

Si no sabe:

```text
"Eso prefiero que te lo confirme la persona encargada."
```

La derivación segura es preferible a inventar.

## 9. Privacidad pública

Antes de instalar en un comercio externo debe estar validado que:

- modo público no recupera recuerdos privados;
- cámara no guarda video automáticamente;
- micrófono no guarda audio continuo automáticamente;
- conversaciones se almacenan según política visible;
- el administrador puede borrar/exportar memoria;
- cloud recibe contexto mínimo;
- el producto puede explicar de forma simple qué datos maneja.

## 10. Hardware físico

Una unidad vendible debe:

- ser eléctricamente segura;
- no contener una batería hinchada/envejecida innecesaria;
- conservar disipación adecuada;
- tener cableado fijo/protegido;
- poder apagarse/reiniciarse de manera controlada;
- ocultar el aspecto de notebook si se usa carcasa propia;
- permitir mantenimiento sin destruir la carcasa.

## 11. Soporte

Antes de piloto externo debe existir:

- identificación de versión;
- health local;
- logs redactados;
- backup/restore;
- rollback;
- procedimiento de recuperación;
- forma de comprobar micrófono/cámara/audio desde panel;
- matriz de hardware soportado.

## 12. Criterio de éxito del piloto

No se mide por cantidad de funciones.

Se considera prometedor si:

- funciona una jornada sin intervención técnica repetitiva;
- clientes comprenden que pueden hablarle;
- los saludos no resultan molestos;
- las respuestas básicas son correctas;
- la latencia se siente natural;
- el costo cloud es bajo/predecible;
- el comerciante puede configurar lo básico desde el celular;
- soporte/actualización no requiere desmontar la unidad;
- la presencia física genera interés real.
