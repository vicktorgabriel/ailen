# Baseline de seguridad — AILEN

## Alcance

AILEN combina micrófono, cámara, memoria, red y proveedores de IA; por eso la seguridad forma parte del producto desde el prototipo.

## Reglas iniciales

- administración web accesible sólo desde LAN por defecto;
- login obligatorio;
- contraseñas almacenadas mediante hash robusto;
- sesiones con expiración;
- rate limit/lockout del login;
- secretos separados de configuración pública;
- ningún token en Git;
- tools mediante allowlist;
- sin shell general para LLM;
- argumentos de tools validados por código;
- memoria local por defecto;
- contexto cloud mínimo;
- logs redactados;
- modo `SHOP/PUBLIC` separado de memoria privada;
- actualizaciones verificadas antes de activar;
- rollback si la nueva versión no pasa health.

## Cámara y micrófono

El usuario debe poder:

- desactivar cámara;
- desactivar micrófono;
- ver estado actual desde panel;
- controlar si se guardan capturas/grabaciones;
- borrar datos persistentes relacionados.

La detección de presencia del MVP no implica identificación biométrica.

## Multi-node

Cuando se implemente:

- pairing explícito;
- identidad de dispositivo;
- revocación;
- autenticación mutua o mecanismo equivalente;
- no confiar en cualquier host de la LAN sólo por estar en la red.

## API cloud

- limitar presupuesto;
- registrar consumo sin guardar secretos;
- no enviar base de datos completa ni historial total;
- separar proveedor de la identidad de AILEN.

## Pendientes

- threat model detallado;
- política de retención;
- esquema de permisos por tool;
- formato de secretos;
- estrategia de firma de releases;
- protección CSRF según framework elegido;
- estrategia de gateway cuando existan varios nodos.
