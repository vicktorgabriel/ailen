# Adaptive appliance provisioning, updates, and LAN hub

- **Status:** Approved design; implementation pending
- **Date:** 2026-08-31
- **Scope:** product provisioning, recoverable updates, adaptive local inference,
  expressive TTS, and optional LAN delegation
- **Related decisions:** ADR-008, ADR-010, ADR-011, ADR-012

## 1. Context

AILEN is one product intended to reuse heterogeneous computers. A recycled
4-8 GB node must remain useful without a dedicated GPU, Internet, or another
AILEN node. A larger installation must use the extra hardware instead of being
artificially limited to the lowest tier. A capable node may also provide LLM
inference and expressive TTS to paired AILEN nodes on the same LAN.

ASRock is a laboratory. Its RTX 3060 and 48 GB of RAM may validate a full node
and LAN hub, but cannot establish support for Bangho, SF20BA, integrated-GPU,
or generic recycled hardware. A hardware class becomes supported only after a
physical benchmark on that class.

The repository already contains useful boundaries: hardware adapters,
`HardwareDetector`, an inference recommender, a GGUF catalog and downloader,
a model planner, a managed llama.cpp runtime, AI routing, a LAN inference
client, a lightweight Chatterbox HTTP client, and a local administration
panel. It does not yet contain a production updater, a complete provisioner,
or the persistent Chatterbox service.

## 2. Goals

1. Ship the same Core and product identity on constrained and powerful nodes.
2. Keep identity, memory, permissions, tools, and policy local to every node.
3. Provide a bounded offline conversation tier on supported 4-8 GB hardware.
4. Exploit CPU, RAM, dedicated GPU, and VRAM when they are actually usable.
5. Let a full node serve LLM and Chatterbox to explicitly paired LAN clients.
6. Let every LAN client fall back to its autonomous local profile.
7. Offer direct third-party APIs or a future managed AILEN subscription without
   making either mandatory.
8. Select artifacts declaratively and verify every downloaded byte.
9. Update code and large assets independently, with health-gated rollback.
10. Expose installation, topology, models, voice, and updates through the
    existing lightweight authenticated Web application.

## 3. Non-goals

- Certifying a minimum hardware tier from an ASRock result.
- Choosing Qwen or any other model family in central Core logic.
- Installing all optional runtimes on every machine.
- Loading Torch or Chatterbox weights in the AILEN Core process.
- Making a client dependent on a LAN hub or cloud provider for basic operation.
- Letting a hub execute tools, access another node's database, or own identity.
- Bundling GGUF, Chatterbox weights, FacePack, or native libraries in the Python
  wheel.
- Treating an artifact that fits in RAM as proven real-time.
- Supporting 32-bit appliances in the initial product baseline.
- Introducing Docker as an appliance requirement.

## 4. Node roles

Roles describe enabled capabilities, not separate editions.

| Role | Required local capabilities | Optional delegation |
|---|---|---|
| `EDGE_STANDALONE` | Core, SQLite, tools, Vosk, Piper, FacePack where a display exists, and a validated small GGUF | direct API |
| `EDGE_LAN_CLIENT` | everything in `EDGE_STANDALONE` | paired LAN LLM and/or Chatterbox, then direct API |
| `FULL_NODE` | local higher-tier GGUF and, when measured viable, local Chatterbox | direct API |
| `LAN_HUB` | authenticated inference and/or TTS services | none required |
| `SATELLITE` | Core and the locally viable deterministic/audio/display subset | paired LAN or explicitly authorized API |

A capable machine can be `FULL_NODE` and `LAN_HUB` simultaneously. Roles are
stored in a generated capability plan. They do not branch Core behavior by
machine model or hostname. These composable service roles do not replace the
existing `DeviceProfile`; provisioning maps one detected/recommended profile to
zero or more roles.

The three existing axes have distinct authority and are recorded separately:

| Axis | Values | Meaning |
|---|---|---|
| `DeviceProfile` | `SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN` | deployment/topology policy |
| `InferenceProfile` | `RULE_ONLY`, `FAST`, `BALANCED`, `QUALITY` | measured inference capacity ceiling |
| `ActiveRoles` | any compatible subset of the roles above | services actually enabled on this node |

The baseline mapping is policy, not a hardware-size promise:

| `DeviceProfile` | Allowed inference ceiling | Candidate active roles |
|---|---|---|
| `SATELLITE` | `RULE_ONLY` | `SATELLITE` |
| `CLOUD` | `RULE_ONLY` unless separately measured | `SATELLITE` |
| `HYBRID` | `FAST` or `BALANCED` when measured | `EDGE_STANDALONE`, optionally `EDGE_LAN_CLIENT` |
| `LOCAL` | measured `FAST`, `BALANCED`, or `QUALITY` | `EDGE_STANDALONE` or `FULL_NODE`, optionally `LAN_HUB` |
| `LAN_BRAIN` | measured `BALANCED` or `QUALITY` | `FULL_NODE`, `LAN_HUB` |

The planner may lower any inferred ceiling or omit a role. It cannot raise one
past measured capability merely because a topology requests it.

An installation cannot be advertised as `EDGE_STANDALONE` until at least one
cataloged GGUF passes the target hardware-class acceptance benchmark. Until
then it is `UNMEASURED` and can be used only as a laboratory/experimental
profile. A node with no accepted local model remains useful for deterministic
tools, Vosk, Piper, and administration, but its offline conversation limitation
must be stated honestly.

## 5. Runtime topology and authority

```text
AILEN Core on every node
  |- identity, memory, policy, tools, routing
  |- Vosk and Piper baseline
  |- local llama.cpp service when provisioned
  |- LAN inference client when paired
  |- Chatterbox HTTP client when configured
  `- direct external provider client when authorized

Optional full/hub node
  |- ailen-inference-service
  `- ailen-expressive-tts-service
```

The two hub services are stateless execution resources from Core's point of
view. They accept normalized bounded requests and return generated text,
metadata, or PCM. They never open client SQLite files, call tools, inspect
configuration, or access the LLM prompt builder directly.

Tool requests or facial metadata returned by any LLM remain untrusted bounded
data. The client Core validates them against its allowlists and permissions.

## 6. Capability detection and activation

### 6.1 Evidence levels

AILEN distinguishes four things that must not be collapsed:

1. `DETECTED`: hardware facts obtained from OS adapters.
2. `RECOMMENDED`: a catalog entry appears compatible on paper.
3. `MEASURED`: the artifact completed a benchmark on this node.
4. `ACTIVE`: the administrator approved the measured plan and health passed.

The Web UI and API expose these terms verbatim. Neither an installed binary nor
available RAM is sufficient for `READY`.

### 6.2 Inputs

The planner consumes:

- OS and architecture;
- CPU architecture, instruction flags, physical/logical cores;
- total and currently available RAM;
- dedicated GPU backend, total/free VRAM, and driver capability;
- integrated/shared GPU status and reserved system-memory margin;
- available disk and filesystem permissions;
- display, audio, and camera facts relevant to the chosen role;
- administrator policy, including offline requirement and maximum disk use;
- catalog requirements and previously recorded benchmarks.

Integrated GPU memory is not counted twice. If reliable shared-memory facts are
unavailable, the planner reserves system RAM conservatively and reports the
uncertainty.

### 6.3 Post-install benchmark

After downloading but before activation, a synthetic public benchmark records:

- peak and steady RSS;
- VRAM use where observable;
- swap activity and major page faults;
- cold and warm startup;
- prompt evaluation and time to first text;
- generation throughput and completion rate;
- deterministic completion/format checks, schema validity, and bounded
  repetition/degeneration checks over public Spanish prompts;
- TTS model load, first PCM, total synthesis, and realtime factor;
- CPU utilization and thermal throttling indicators where observable.

Naturalness, dialect, empathy, and conversational usefulness are separate human
qualification gates run when accepting a model for a hardware class. They are
not presented as deterministic post-install checks or delegated to an external
evaluator on an offline appliance.

Thresholds live in a versioned capability catalog for a declared hardware
class. They are not global constants inferred from ASRock. An administrator may
activate an unmeasured candidate only in an explicit `experimental` mode; that
does not create a support claim or alter the stable catalog.

## 7. Signed manifests and artifact catalog

AILEN uses three versioned documents.

### 7.1 Release manifest

The release manifest declares:

- release version and update channel;
- supported OS/architecture;
- Core wheel and platform artifacts;
- minimum config schema, database schema, FacePack format, and native ABI;
- artifact URL, byte size, SHA-256, and detached Ed25519 signature;
- health gates, compatible rollback targets, and release notes.

### 7.2 Capability catalog

Model and voice entries declare at least:

- stable artifact ID, version, family, purpose, and license;
- runtime and format such as GGUF/llama.cpp or Chatterbox service assets;
- quantization, context defaults, and expected disk size;
- CPU/GPU/OS/architecture requirements;
- conservative RAM/VRAM envelopes;
- approved download origins, exact byte size, SHA-256, and signature;
- candidate roles and evidence status per hardware class;
- benchmark policy version;
- known incompatibilities and distribution restrictions.

Adding Gemma, Llama, Qwen, SmolLM, or a future family adds or updates catalog
data and tests. It does not add `if model == ...` logic to Core.

### 7.3 Installation record

Each node stores a non-secret record of the detected hardware snapshot,
approved plan, artifact hashes, benchmark summary, active release, rollback
release, and active service roles. Secrets and raw benchmark prompts/responses
are excluded.

Manifest verification is fail-closed. URLs supplied by an LLM, an untrusted
Web request, or an unsigned catalog are never passed to a downloader.
Release trust starts from an AILEN signing public key installed with the
appliance image. Key rotation requires a manifest signed by the currently
trusted key and the incoming key; simply downloading a new public key cannot
change the trust root.

## 8. Provisioning flow

The canonical flow is:

```text
detect
 -> plan
 -> display artifacts, sizes, licenses, and limitations
 -> operator approval
 -> reserve disk and create staging
 -> download or import signed offline bundle
 -> verify size, hash, signature, and path safety
 -> install without activation
 -> benchmark
 -> present measured plan or safe downgrade
 -> operator activation
 -> service health probation
 -> retain or roll back
```

Lab Mode always requires explicit approval before downloading. Appliance Mode
may execute an already approved plan automatically during first installation;
the onboarding UI must still have shown the artifacts, licenses, and total
download size before approval.

The artifact store is content-addressed. Identical weights are not duplicated.
Partial downloads live only in staging, support bounded resume, and are never
made active before full verification. Garbage collection is explicit and cannot
remove the active or rollback artifact set.

An offline bundle imported from local media follows the same manifest,
signature, staging, benchmark, and activation path as an online download.

## 9. Recoverable updater

### 9.1 Filesystem boundary

```text
/opt/ailen/releases/<version>/
/opt/ailen/current -> /opt/ailen/releases/<version>
/etc/ailen/ailen.toml
/var/lib/ailen/ailen.db
/var/lib/ailen/artifacts/<sha256>/
/var/lib/ailen/provisioning/
/var/lib/ailen/secrets/
/run/ailen/
```

Application releases are immutable. Configuration, secrets, models, voices,
database, and mutable state remain outside release directories.

### 9.2 Service boundary

`ProvisioningService` creates plans and exposes status without elevated
privileges. A narrow appliance-only `ailen-updaterd` performs allowlisted
filesystem and systemd operations through an authenticated local Unix socket.
The Web process cannot run arbitrary shell commands or manipulate symlinks.
On Debian, the socket is mode `0660`, owned by the dedicated updater service and
AILEN administration group. The daemon verifies kernel-supplied peer UID/GID
through `SO_PEERCRED` and still validates every operation against its narrow
schema; possession of filesystem access alone cannot authorize arbitrary shell.

The updater contract is:

```text
check(channel) -> UpdateInfo
plan(version) -> UpdatePlan
download(plan) -> OperationId
status(operation_id) -> OperationStatus
cancel(operation_id) -> CancelResult
activate(prepared_release) -> ActivationResult
rollback() -> RollbackResult
```

Operations are journaled without secrets so an interrupted download or reboot
can resume or fail cleanly.

### 9.3 Activation and rollback

Activation installs in parallel, runs preflight, applies compatible migrations,
switches `current` atomically, restarts only affected services, and observes a
bounded health probation. Failure switches back to the previous release and
records the exact failed gate.

Automatic and standard stable updates accept only expand/contract migrations
whose resulting schema remains readable by the declared rollback release. A
health failure therefore switches code back while retaining the compatible
schema and all writes made during probation.

A migration that makes the rollback release unable to read the database is not
eligible for the normal updater path, even if a down-migration appears possible.
It requires an explicit major-conversion workflow with verified backup, restore
drill, maintenance window, and administrator acknowledgement that automatic
rollback is unavailable. Standard rollback never executes a down-migration or
silently restores an older snapshot that would discard probation writes. The
updater never deletes `/var/lib/ailen` or overwrites secrets/config wholesale.

Code, model, voice, and FacePack updates are independent artifact operations.
Updating Core does not re-download unchanged large assets. Changing a model or
voice requires size/license disclosure and confirmation even when automatic
software installation is enabled.

### 9.4 Channels

- `nightly`: laboratory, manual activation.
- `beta`: prototypes/pilots, notification plus confirmation.
- `stable`: automatic checks, configurable scheduled activation, health-gated
  rollback.

Stable defaults to notifying before feature updates. An administrator may opt
into scheduled unattended activation. Model/voice profile changes remain
approval-gated.

## 10. LAN discovery, pairing, and transport

An enabled hub advertises `_ailen._tcp` through mDNS with only node name,
service version, address, and coarse capabilities. Manual address entry remains
available when discovery is unavailable. Discovery grants no trust.

Pairing requires:

1. an authenticated administrator on the client;
2. a one-use bounded-expiry code displayed by the hub;
3. explicit acceptance on the client;
4. TLS certificate fingerprint pinning;
5. a unique revocable client token scoped to `inference`, `tts`, or both.

Hub endpoints bind to loopback by default. LAN binding requires explicit hub
enablement. Requests use HTTPS; certificate rotation requires an authenticated
re-pair or a signed rotation procedure. Tokens are stored in the existing
0600 secret store and are never included in logs or process arguments.

The hub rate-limits each client and exposes bounded queue depth. It does not
persist prompts or PCM. Operational metrics contain request IDs, sizes,
latencies, model IDs, and error classes only.
Every request ID is owned by the authenticated `client_id` derived from its
token. Read, status, and cancellation operations verify that ownership. Queue
depth, in-flight concurrency, request rate, and PCM/text output budgets are
bounded per client as well as globally, preventing one paired node from starving
or cancelling another.

## 11. LAN inference service

The service keeps one provisioned GGUF resident per configured execution slot.
It exposes versioned health/capability metadata and an OpenAI-compatible text
generation endpoint so the existing LAN backend can remain the client boundary.
Advertised capabilities must match implemented behavior; streaming is true only
when deltas arrive while generation is active.

The internal `AiRequest` is never handed directly to a LAN or external adapter.
Core's outbound privacy boundary constructs a distinct `OutboundAiRequest` type
whose schema cannot contain retrieved memory, notes, secrets, local paths, or
unrestricted history. Default LAN privacy sends the current turn, a bounded
non-secret conversational context, public style instructions, and only the tool
schemas needed for that turn. A trusted LAN setting may widen the ephemeral
conversational window, but never grants database/filesystem access or server-side
retention. Tests capture the final serialized payload, not merely a policy flag.

Routing uses health, current queue, exponentially weighted first-text latency,
privacy, and administrator priority. A circuit breaker skips a failed hub
quickly. Recovery uses a bounded probe before normal traffic resumes.

Fallback order is explicit per node. For an `EDGE_LAN_CLIENT` it is normally:

```text
paired LAN -> local GGUF -> authorized direct API -> honest degraded Core
```

No disabled route is enabled implicitly.

## 12. Local LLM runtime

GGUF through a managed llama.cpp service is the canonical appliance baseline.
Ollama may remain a Lab adapter but is not required on sold appliances. The
runtime is loopback-only unless the node is deliberately enabled as a hub.

The provisioner chooses among signed catalog candidates by purpose and measured
behavior, not family name. Context, batch size, thread count, and GPU layers are
part of the generated plan. They are bounded by available memory and are kept
stable for the session to avoid swapping and repeated cold starts.

On Debian, Core, local inference, and expressive TTS run in separate systemd
services/slices. Core is protected as the authority and deterministic fallback;
model services receive plan-derived `MemoryHigh`/`MemoryMax` budgets and a lower
OOM survival priority. Exact limits and OOM adjustments are catalog/profile data
validated on the hardware class, not constants copied from ASRock. Exceeding a
model budget degrades that capability instead of inviting the kernel to kill
Core or the graphical session.

Before stable shipment for a 4 GB or 8 GB hardware class, at least one candidate
must pass the complete physical acceptance suite with Vosk, Piper, FacePack, Web,
SQLite, and representative background load active. A standalone claim cannot be
based on an isolated llama.cpp benchmark.

## 13. Expressive TTS service

`ailen-expressive-tts-service` is a separate Python environment/process. It
loads the approved Chatterbox LatAm assets once and imports Torch only inside
that service. The Core wheel and process remain lightweight.

The versioned contract exposes:

```text
GET  /health
GET  /capabilities
POST /synthesize
POST /cancel/<request_id>
```

Health is `READY` only after the selected model is loaded and a bounded
self-test has succeeded. It reports model/artifact ID, output PCM format,
device class, readiness, queue depth, and non-secret performance summary.

The first implementation is honest about Chatterbox generation: it synthesizes
short completed text fragments and returns canonical PCM. It does not label a
fully buffered waveform as neural streaming. Conversation fluency comes from an
early LLM phrase, one-fragment bounded prefetch, and immediate playback. The
queue never synthesizes an entire long answer ahead.

Barge-in cancels queued requests and playback immediately. If the currently
executing Torch operation cannot be preempted safely, the service discards its
result and reports cancellation rather than playing stale audio. The client
falls back to local Piper after health failure or circuit opening.
Cancellation is authorized only for the `client_id` that owns the request; an
unrelated paired node receives `403` and cannot cancel another conversation.

The ASRock deployment is the first `FULL_NODE + LAN_HUB` laboratory target. Its
results describe ASRock only. CPU and lower-memory Chatterbox support remain
`UNMEASURED` until tested on those classes.

## 14. External APIs and managed subscription

Direct external providers remain interchangeable Router backends. A customer
may supply a provider-specific key, or a future AILEN subscription may issue a
distinct managed credential. ChatGPT subscriptions, CLI logins, and unrelated
provider credentials are never treated as API entitlement.

External routing is optional and explicit. The current external-provider work
continues to enforce separate secrets, real capabilities, bounded timeouts,
rate-limit cooldown, and sanitized payloads. Local or LAN inference is never
disabled merely because a remote provider exists.

## 15. Data architecture

### 15.1 Per-node authority

SQLite remains the canonical database on every AILEN node. Replacing it with a
database server on recycled hardware would add memory, processes, administration,
and failure modes without improving the expected single-node workload.

The appliance SQLite profile requires:

- one logical application owner for writes;
- WAL, foreign keys, and a bounded busy timeout;
- `synchronous=FULL` for persistent customer data in Appliance Mode;
- owner-only file permissions and secrets stored outside the database;
- FTS5 as the canonical textual-memory index;
- explicit transactions at repository/application-service boundaries;
- bounded retention for conversations, audit events, and metrics;
- no placement on NFS, SMB, or another network filesystem.

If the appliance SQLite build lacks FTS5, memory search is reported as degraded
and is not silently replaced by a divergent production search implementation.
Lab experiments may still compare alternatives without changing the appliance
contract.

### 15.2 Integrity, migration, and backup

Database health distinguishes connectivity from integrity. Normal health uses a
cheap bounded check; update/backup workflows create an online SQLite backup into
staging, run `quick_check` on that snapshot, and only then publish the archive.
Periodic maintenance or suspected corruption may run a full `integrity_check`
outside the latency-sensitive conversation loop.

Copying only the live main database file while WAL is active is prohibited.
Backups use SQLite's online backup API, include the schema and non-secret
installation metadata, and are restored in automated tests before being called
valid.

Every schema migration has a pre-migration verified snapshot, executes
atomically with its `schema_meta` record, and declares the oldest release that
can still read the resulting schema. Expand/contract is the default. A migration
that cannot support automatic rollback blocks unattended activation unless it
ships a separately tested reverse operation.

### 15.3 Search and future semantic retrieval

FTS5 is sufficient for the expected per-assistant corpus and remains the first
retrieval layer. A vector database is not introduced without a measured corpus
and retrieval-quality need. A future embedding index may be an optional derived
artifact that can be rebuilt from SQLite; it can never become the authority for
memory.

### 15.4 Hub and commercial control plane

LAN inference and Chatterbox services are stateless with respect to their
clients and never open or replicate client databases.

A future commercial fleet/subscription backend may use PostgreSQL for customer
accounts, device enrollment, subscriptions, signed release assignments, and
consented aggregate telemetry. It is a separate control plane, not a replacement
for node SQLite. Nodes exchange bounded signed events through an outbox/API and
continue operating when the control plane is unreachable.

## 16. Administration backend and Web UI

The existing authenticated lightweight Web application remains canonical. It
calls application services; handlers do not manipulate files, systemd, model
processes, or raw SQLite directly.

### 16.1 Pages

- **Setup:** detected facts, recommendation, uncertainty, downloads, licenses,
  and approval.
- **Models:** installed/active/rollback artifacts, size/hash/license, measured
  performance, status, activate, and remove when safe.
- **Voice:** Piper and Chatterbox local/LAN status, first PCM, realtime factor,
  fallback, and test synthesis using public synthetic text.
- **Nodes:** discovery, manual address, pairing, scopes, health, queue, latency,
  priorities, and revocation.
- **Updates:** channel, release notes, plan, progress, schedule, activate, health,
  and rollback.
- **Diagnostics:** selected/effective LLM and TTS, reason codes, resource use,
  circuit state, and fallback cause.
- **External AI:** customer APIs or managed subscription, privacy and cost.

### 16.2 API behavior

State-changing endpoints require authentication, CSRF protection, narrow input
schemas, and authorization. Long operations return an operation ID and progress
is polled or streamed as status events. Browser disconnects do not terminate the
operation or crash the Web server.

The UI never promises hot reload when a controlled service restart is required.
It distinguishes `DETECTED`, `RECOMMENDED`, `UNMEASURED`, `DOWNLOADING`,
`INSTALLED`, `READY`, `DEGRADED`, `UNAVAILABLE`, and `ROLLBACK_AVAILABLE`.

## 17. Failure behavior

- Unknown hardware facts produce an `UNMEASURED` plan, not an optimistic tier.
- Insufficient disk blocks staging before download.
- Invalid size/hash/signature deletes or quarantines only the staged artifact.
- Failed benchmark leaves the previous runtime active.
- Failed service activation restores the previous service artifact/config.
- LAN timeout opens a circuit and uses the next explicitly configured route.
- Chatterbox failure falls back to Piper without changing the facial affect
  contract.
- No LLM route yields an honest degraded response and deterministic tools remain
  available.
- Updater failure never deletes mutable customer data.

## 18. Observability and data minimization

Structured, content-free telemetry records:

- node and session IDs that do not identify a customer externally;
- requested/effective route and artifact ID;
- hardware-class evidence status;
- setup, first-text/first-PCM, total latency, throughput, and queue delay;
- RSS/VRAM/swap summaries;
- fallback and typed failure reason;
- update phase, health gate, activation, and rollback result.

Prompts, generated text, PCM, camera frames, passwords, tokens, private memory,
and raw customer configuration are excluded from provisioning/update metrics.

## 19. Validation

### 19.1 Automated

- deterministic hardware-profile planning with fake reports;
- integrated/shared GPU memory accounting;
- signed manifest and catalog parsing, versioning, path safety, size, hash, and
  corrupt/out-of-range cases;
- download resume, cancellation, insufficient disk, and no partial activation;
- content-addressed deduplication and protected rollback assets;
- interrupted update recovery, atomic switch, health failure, and rollback;
- config/database persistence across release changes;
- SQLite online backup under WAL, snapshot integrity, restore, atomic migration,
  and incompatible-schema rollback blocking;
- FTS5 availability and bounded memory retrieval;
- service privilege boundary and Web authorization/CSRF;
- LAN discovery without trust, pairing expiry, fingerprint pinning, token scopes,
  revocation, per-client/global rate and queue limits, request ownership, and
  cross-client cancellation rejection;
- sanitized LAN payload capture;
- hub failure/cooldown/recovery and autonomous fallback;
- Chatterbox load health, synthesis, cancellation, queue bounds, Piper fallback,
  and absence of Torch in the Core process;
- dynamic addition of a model/voice catalog entry without Core changes;
- offline signed-bundle import through the same verification path;
- wheel/release inspection without model weights, raw media, secrets, or mutable
  customer data.
- cgroup memory-limit breach of a model service without loss of Core;

### 19.2 Physical gates

Each hardware class is tested end-to-end, not by extrapolation:

- 4 GB recycled target;
- 8 GB recycled target;
- integrated-GPU target where available;
- ASRock full node/hub;
- at least one client-to-hub LAN session plus deliberate hub loss;
- update success, failed health rollback, and power interruption recovery.

The test runs Vosk, active display/FacePack where applicable, Piper or
Chatterbox, SQLite, Web, tools, and conversation together. Results publish
hardware identity, profile, versions, load conditions, latency distributions,
RSS/swap, thermals where available, and unresolved limitations.

## 20. Implementation verticals

### Vertical 1: release and update foundation

- schemas and verifier for release/capability manifests;
- content-addressed artifact store and staging;
- `ProvisioningService` plans and operation journal;
- updater simulation with atomic activation/rollback in a temporary root;
- authenticated Web status and update-plan screens.

No real appliance path is activated until destructive/path-safety tests pass.

### Vertical 2: onboarding and adaptive assets

- connect existing hardware detector, model planner, downloader, and speech
  assets to the signed catalog;
- present approval, download, benchmark, and activation in the Web setup;
- generate an installation record and explicit local configuration;
- preserve a fully offline bundle path.

This vertical precedes claims on newly acquired recycled hardware.

### Vertical 3: expressive TTS and LAN hub laboratory

- persistent Chatterbox service outside Core;
- local client health/synthesis/cancel integration;
- authenticated LAN gateway, discovery, and pairing;
- bounded phrase prefetch and Piper fallback;
- ASRock-only latency, memory, barge-in, and multi-client measurements.

### Vertical 4: local LLM candidate qualification

- curate several licensed GGUF candidates across families;
- benchmark them on each actual 4/8 GB target with the complete AILEN workload;
- publish accepted profile entries or honest rejection results;
- never promote an ASRock-only result to a constrained profile.

### Vertical 5: Debian appliance hardening

- reproducible Debian 13 package/image inputs;
- dedicated users, systemd services, Unix-socket authorization, and kiosk start;
- signed release delivery, scheduled stable updates, health probation, and
  rollback;
- installation, recovery, and support documentation.

## 21. Acceptance criteria

The architecture is delivered when all of the following are demonstrated:

1. One release can provision different roles solely from a signed catalog and
   measured plan.
2. A new GGUF family or voice can be added without editing Core routing logic.
3. Model/voice downloads require informed approval and are fully verified.
4. A failed code update rolls back without losing config, secrets, models, or
   SQLite data.
5. A supported standalone recycled node converses offline using its validated
   local GGUF and Piper.
6. The same node can use a paired hub and return locally after hub loss.
7. ASRock can keep Chatterbox resident and serve authenticated LAN clients while
   Core stays Torch-free.
8. External APIs remain optional and separately authorized.
9. The Web panel reports selected versus effective capabilities and never
   fabricates health or support.
10. Documentation and benchmark records distinguish laboratory evidence from
    product support.

## 22. Documentation impact

After implementation begins, this design results in:

- a new ADR for signed provisioning, artifact lifecycle, and LAN service trust;
- updates to ADR-010 for evidence-level terminology and role composition;
- updater and recovery runbooks;
- appliance installation and offline-bundle documentation;
- model/voice catalog authoring and review documentation;
- target-specific benchmark reports;
- current-state, roadmap, tasks, changelog, and agent handoff updates.

Historical benchmark claims remain historical and are not rewritten as current
support guarantees.
