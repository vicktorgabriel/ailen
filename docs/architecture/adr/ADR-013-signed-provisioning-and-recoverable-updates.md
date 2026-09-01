# ADR-013 — Signed provisioning and recoverable updates

**Status:** Accepted for the R6 Vertical 1 Lab foundation  
**Date:** 2026-08-31  
**Production boundary:** Appliance activation remains disabled until a narrow
privileged `ailen-updaterd` exists and is validated on dedicated hardware.

## Context

AILEN must update recycled appliances without requiring Git, overwriting the
running installation in place, or allowing the Web process to perform privileged
filesystem/service operations. A failed download, corrupt artifact, interrupted
process, unhealthy candidate or power loss must not silently turn into a partial
installation. Model, voice and FacePack artifacts will eventually use the same
trust vocabulary, but they are not provisioned by this first vertical.

The update UI is an untrusted administrative input boundary. It may request a
bounded operation, but it may not choose paths, URLs, hashes, commands or system
services. Those values come only from locally configured trust roots and a signed
manifest.

## Decision

1. Release metadata uses an exact, bounded JSON manifest. Duplicate keys,
   unknown fields, unsafe identifiers/URLs, invalid sizes and incompatible schema
   ranges fail closed before any action.
2. A detached Ed25519 signature authenticates the exact manifest bytes. The
   implementation invokes the installed OpenSSL binary with an argv vector,
   file-descriptor-backed regular files, `O_NOFOLLOW`, strict size limits and a
   three-second timeout. OpenSSL stderr and filesystem paths never cross the
   public boundary.
3. Artifact URLs, sizes, SHA-256 digests, expanded-size limits, platform and
   media type are inside the signed manifest. Every download is size/hash checked
   before entering immutable content-addressed storage (CAS), and extraction
   verifies the object again.
4. Downloads are bounded, cancellable and resumable through ETag plus
   `Range`/`If-Range`. Resume metadata contains no URL or secret. A new process
   must fetch and verify the manifest again and obtain a new short-lived approval
   before resuming an interrupted operation.
5. One JSON journal record per operation persists the exact state machine:
   `PLANNED -> DOWNLOADING -> VERIFIED -> PREPARED -> ACTIVATING -> PROBATION ->
   ACTIVE`, with typed terminal failure/cancellation/rollback states. Writes use
   private directories, fixed schemas, atomic replacement and fsync. Only one
   worker or activation operation may be active in a service instance.
6. Release extraction accepts only bounded regular files/directories from the
   verified tar artifact. Absolute/traversal paths, links, devices, FIFOs, sparse
   entries, duplicates and path collisions are rejected. A release is prepared
   in a private staging directory and renamed atomically.
7. Activation switches a `current` symlink atomically only after preflight,
   starts the injected service boundary, then waits through health probation. A
   failed candidate restores and restarts the previous release. Both immutable
   releases and their artifacts remain available for diagnosis/rollback.
8. Database migrations for an update must be forward and rollback compatible
   according to the signed schema ranges. Automatic database restore or down-
   migration is not part of rollback. A release that cannot preserve compatible
   persistent data is rejected before service mutation.
9. The Python/Web process owns unprivileged checking, planning, download,
   verification, preparation and DTO projection. A future privileged daemon owns
   only the narrow real activation/service boundary. Web handlers call
   `UpdateAdminService`; they never run a shell, unpack archives or receive
   filesystem paths.
10. The current factory implements `LAB_SIMULATION` under injected repository
    runtime roots. It never invokes systemd or writes appliance paths. Asking for
    Appliance mode returns an honest disabled service until `ailen-updaterd`
    exists.
11. Update source/trust configuration is optional and incomplete configuration
    disables the service without network access. Construction is side-effect
    free; no directory, thread, check or download is created during Web startup.
12. The authenticated `/actualizaciones` page and `/api/updates/*` endpoints use
    CSRF protection, exact field allowlists, bounded identifiers and redacted
    typed responses. Closing the browser never cancels the independent worker.

## Implemented evidence

The acceptance test creates an ephemeral Ed25519 key, signs exact manifest
bytes, serves all bytes through injected in-memory transports, downloads into
CAS, prepares a temporary release, switches a temporary `current` link and runs
synthetic health probation. Separate scenarios prove automatic rollback from an
unhealthy signed candidate and ETag/range resume after interruption and fresh
manifest verification/approval. It touches no Internet endpoint, `/opt`,
systemd or live database.

This evidence establishes the software contracts only. It does not establish a
production signing ceremony, power-loss durability on real media, hardware
support, or a safe privileged appliance daemon.

## Consequences

Positive:

- authenticity precedes parsing/action and artifact integrity is traceable to a
  signed manifest;
- downloads and releases are immutable/recoverable rather than in-place;
- Web compromise does not directly grant shell/systemd/archive primitives;
- interrupted work is observable and must be reauthorized;
- Lab can exercise the complete logical lifecycle without mutating the host.

Costs and limitations:

- OpenSSL is an explicit runtime dependency for signature verification;
- CAS temporarily keeps multiple releases and needs a later retention/GC policy;
- only the Lab controller exists; real service ownership and privilege
  separation remain unimplemented;
- the release signing pipeline, offline bundle CLI, fleet policy, model/voice
  provisioning and physical power-loss testing remain future work;
- no stable channel is enabled automatically by this ADR.

## Rejected alternatives

- **Unsigned or hash-only manifests:** a hash obtained from the same compromised
  source authenticates nothing.
- **Web handlers invoking shell/systemd/tar:** collapses the privilege and input
  boundaries and makes CSRF/request parsing a system mutation interface.
- **In-place overwrite:** leaves ambiguous mixed versions after interruption and
  prevents a reliable atomic rollback.
- **Automatic database down-migration/restore:** risks destroying user memory and
  configuration; compatibility must be proven before activation instead.
- **Packaging model weights, voices or FacePacks in the Python wheel:** makes the
  wheel hardware-specific and prevents independent signed artifact lifecycle.
