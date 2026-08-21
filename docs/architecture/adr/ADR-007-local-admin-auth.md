# ADR-007 — Autenticación administrativa persistente del panel local

**Estado:** Accepted
**Fecha:** 2026-08-21

## Contexto

El panel web necesita una credencial administrativa que sobreviva reinicios.
El baseline previo (`FakeAuthService` + `AILEN_ADMIN_PASSWORD`) es correcto
para desarrollo pero no como base del producto: la contraseña vive en el
entorno del proceso, no hay gestión de alta/cambio sin editar servicios, y no
queda rastro auditable de cuándo se creó.

Restricciones:

- cero dependencias externas mientras el stack no esté cerrado (ADR-006);
- hardware débil (2–8 GB): el costo de login debe ser acotado;
- fail-closed: sin credencial configurada, el panel no autentica a nadie;
- nada de passwords default ni en claro.

## Decisión

1. **Almacenamiento: SQLite, tabla `admin_credentials` (migración 0002).**
   Misma base del nodo, fila única forzada por `CHECK (id = 1)`. Se guardan
   sólo `password_hash`, `salt`, `kdf`, `iterations` y metadatos. Razones:
   - ya existe infraestructura SQLite con migraciones versionadas y tests;
   - permisos/backup del nodo cubren un único archivo;
   - evita un archivo de secretos adicional con ciclo de vida distinto.
   La alternativa `/var/lib/ailen/secrets/` (ARCHITECTURE §18) sigue abierta
   para API keys cloud; la credencial del panel no la requiere hoy.

2. **KDF: PBKDF2-HMAC-SHA256 con 600.000 iteraciones** (`hashlib.pbkdf2_hmac`,
   stdlib). Es la única KDF de passwords razonable disponible sin dependencias;
   600k alinea con la recomendación OWASP vigente para SHA-256. Costo típico:
   decenas/cientos de ms por intento — aceptable para login administrativo y
   disuasivo offline. Si el stack final incorpora `argon2-cffi`, migrar es una
   fila nueva (`kdf`, `iterations`) + re-hash on first login; el esquema lo
   contempla.

3. **Salt aleatorio de 16 bytes por credencial** (`secrets.token_bytes`);
   regenerado en cada cambio de contraseña.

4. **Comparación constant-time** (`hmac.compare_digest`) entre hash almacenado
   y candidato.

5. **Lockout por IP**: 5 fallos en ventana de 5 minutos => bloqueo de 5 minutos.
   Igual que el baseline; sesiones siguen efímeras en memoria con TTL y token
   CSRF por sesión.

6. **Alta/cambio por CLI explícita**: `ailen admin set-password` lee por
   `getpass` (nunca argv visible en `ps`), exige longitud mínima 8 y doble
   confirmación, y ejecuta migraciones antes de escribir.

7. **Fail-closed**: si no hay credencial, `configured=False` y todo `verify`
   falla; el login muestra instrucciones del CLI. Sin defaults.

8. **No editable desde Web**: host/port del panel tampoco son campos del
   `SettingsService`; cambiar el bind en caliente puede exponer el panel o
   dejar afuera al operador. Se administran por archivo/CLI y aplican al
   reiniciar.

## Consecuencias

- `PersistentAuthService` implementa el mismo contrato `AuthService`;
  handlers y tests no cambian de forma.
- `FakeAuthService` queda para desarrollo/tests puros.
- Deuda aceptada: sesiones no persisten entre reinicios (re-login tras
  reiniciar el nodo); duplicación parcial de lógica lockout/sesión con el fake.
- Migrar a Argon2 u otro KDF no cambia esquema, sólo agrega variante de `kdf`.
