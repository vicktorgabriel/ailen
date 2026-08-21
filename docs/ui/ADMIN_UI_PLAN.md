# Plan de UI administrativa — AILEN

## Principio

No habrá app móvil obligatoria. La administración se realiza desde una web responsive accesible por LAN.

## Primera experiencia

1. el dispositivo inicia;
2. el usuario obtiene dirección/nombre local o entra por mecanismo de setup;
3. crea usuario administrador y contraseña;
4. configura Wi-Fi/red si hace falta;
5. completa información del negocio;
6. elige voz/rostro/modo;
7. configura IA y presupuesto;
8. realiza prueba de micrófono, parlantes y cámara.

## Secciones previstas

### Dashboard

- online/offline;
- uptime;
- RAM/CPU/temperatura;
- Internet;
- backend IA activo;
- cámara/micrófono/audio;
- versión/canal;
- costo API del período.

### Comercio

- nombre;
- descripción;
- horarios;
- servicios;
- formas de pago;
- preguntas frecuentes;
- frases/estilo de saludo;
- cooldown de saludo.

### Personalidad

- rasgos base;
- evolución desactivada/lenta/normal;
- preferencias observadas;
- historial de cambios;
- congelar/restaurar personalidad.

### IA

- modo Cloud/Hybrid/Local;
- proveedores habilitados;
- LAN Brain;
- presupuesto diario/mensual;
- fallback;
- métricas de latencia/costo.

### Audio y cámara

- dispositivos;
- volumen;
- sensibilidad/wake;
- test TTS;
- preview cámara;
- activar/desactivar módulos.

### Memoria

- sesiones;
- recuerdos;
- búsqueda;
- editar/eliminar/exportar;
- política de retención.

### Sistema

- health;
- logs redactados;
- actualización;
- canal;
- backup/restore;
- reinicio/apagado mediante controles autorizados.

## Responsive

La UI se diseña primero para teléfono y se amplía a desktop. Evitar tablas anchas como interfaz principal en móvil.

## Multi-node futuro

El mismo diseño deberá poder mostrar varios asistentes y entrar al detalle de cada nodo sin crear una aplicación separada.
