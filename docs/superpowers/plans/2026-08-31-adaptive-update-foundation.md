# Adaptive Update Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The repository owner explicitly
> forbids commits and pushes during this work, so every task ends with a review
> and test gate instead of a commit.

**Goal:** Build the first product-grade vertical for signed release manifests,
verified content-addressed downloads, recoverable simulated activation, and an
authenticated update page/API without touching real appliance paths.

**Architecture:** A pure application layer parses signed release data and plans
operations; a content-addressed store owns immutable artifacts; an activator
operates only through injected filesystem and service-control boundaries. The
existing lightweight Web application consumes a narrow `UpdateAdminService` and
never performs downloads, extraction, symlink changes, or shell operations from
handlers.

**Tech Stack:** Python 3.11 standard library, OpenSSL 3 Ed25519 verification,
SQLite-independent atomic JSON operation journals, stdlib HTTP/HTML/JavaScript,
pytest, Ruff, and mypy.

**Spec:**
`docs/superpowers/specs/2026-08-31-adaptive-appliance-provisioning-lan-hub-design.md`

## Global Constraints

- Preserve the existing dirty working tree; do not use `git reset`, `restore`,
  `clean`, or bulk deletion.
- Do not commit or push.
- Do not download LLM, TTS, FacePack, H3, or other large production assets in
  this vertical.
- Do not touch FacePack, audio, VAD, STT, TTS, camera, or the Trading Bot.
- ASRock is a laboratory and cannot establish a 4 GB/8 GB support claim.
- Debian 13 amd64 is the appliance baseline; Mint/Windows remain non-mutating
  Lab Mode platforms.
- Core remains owner of identity, memory, permissions, tools, and routing.
- No secret, prompt, PCM, image, API token, signing private key, or customer data
  may enter source, fixtures, logs, manifests, journals, or build artifacts.
- The production trust root is an Ed25519 public key only. Production private
  signing material never enters this repository.
- Manifest URLs must use HTTPS. Unit/integration tests may use an injected local
  byte source rather than weakening the production URL policy.
- `stable` automatic activation accepts only database schemas readable by the
  declared rollback release. No automatic down-migration or silent snapshot
  restore is allowed.
- Web handlers require existing authentication and CSRF protection and return
  typed/redacted errors without filesystem paths or tracebacks.
- Long operations are single-worker and bounded. The update subsystem must not
  create an unbounded thread pool on low-memory hardware.
- This vertical never writes `/opt`, `/etc`, `/var/lib`, systemd, or the live
  `current` symlink. Activation tests use an injected `tmp_path` root.
- Use `apply_patch` for repository file edits.

---

## File structure

### New production modules

- `src/ailen/updates/__init__.py`: stable public imports only.
- `src/ailen/updates/contracts.py`: enums, immutable DTOs, protocols, and typed
  update errors; no I/O.
- `src/ailen/updates/manifest.py`: bounded strict JSON parsing and compatibility
  validation after signature verification.
- `src/ailen/updates/signatures.py`: OpenSSL Ed25519 adapter with no shell and
  no private-key operations.
- `src/ailen/updates/source.py`: HTTPS retrieval of bounded manifest/signature
  bytes followed by verify-before-parse loading.
- `src/ailen/updates/artifact_store.py`: immutable content-addressed objects,
  staging paths, hashing, fsync, deduplication, and protected removal.
- `src/ailen/updates/downloader.py`: HTTPS-only bounded download/resume into
  staging and atomic commit into the artifact store.
- `src/ailen/updates/journal.py`: atomic content-free operation journal.
- `src/ailen/updates/service.py`: planning, one-worker operation lifecycle,
  cancellation, and admin-facing DTO projection.
- `src/ailen/updates/activation.py`: safe archive extraction and atomic release
  activation/rollback against injected boundaries.
- `src/ailen/updates/factory.py`: constructs a disabled, Lab simulation, or
  future appliance update service honestly from configuration.
- `src/ailen/web/templates/updates.html`: authenticated update status and action
  page.

### Existing production files to modify

- `src/ailen/core/config.py`: add non-secret update source/trust/automation
  fields and strict validation.
- `config/ailen.example.toml`: document disabled-by-default update source and
  trust key.
- `src/ailen/web/services.py`: add the `UpdateAdminService` Web boundary and a
  deterministic fake.
- `src/ailen/web/app.py`: inject the service, add page/API routes, enforce CSRF,
  and project errors.
- `src/ailen/web/templates/base.html`: add the Updates navigation item.
- `src/ailen/cli.py`: wire the update service into the existing Web command.
- `docs/architecture/MODULE_CONTRACTS.md`: replace the obsolete synchronous
  updater contract with the operation-oriented contract.
- `docs/deployment/DEPLOYMENT_PLAN.md`: align persistent artifact paths and mark
  real systemd activation as a later vertical.
- `docs/architecture/adr/README.md`: register the new updater/provisioning ADR.
- `docs/architecture/adr/ADR-013-signed-provisioning-and-recoverable-updates.md`:
  record trust, privilege, activation, and rollback decisions.
- `ROADMAP.md`, `TASKS.md`, `CHANGELOG.md`,
  `docs/memory/CURRENT_STATE.md`, and `docs/memory/RECENT_DECISIONS.md`: record
  only behavior actually delivered by this vertical.

### Tests to create or modify

- `tests/unit/test_update_manifest.py`
- `tests/unit/test_update_signatures.py`
- `tests/unit/test_update_source.py`
- `tests/unit/test_update_artifact_store.py`
- `tests/unit/test_update_downloader.py`
- `tests/unit/test_update_journal.py`
- `tests/unit/test_update_service.py`
- `tests/unit/test_update_activation.py`
- `tests/unit/test_update_factory.py`
- `tests/web/test_updates_admin.py`
- `tests/integration/test_update_vertical.py`
- `tests/unit/test_config.py`
- `tests/web/test_http_smoke.py`

---

### Task 1: Immutable update contracts and strict manifest parser

**Files:**
- Create: `src/ailen/updates/__init__.py`
- Create: `src/ailen/updates/contracts.py`
- Create: `src/ailen/updates/manifest.py`
- Test: `tests/unit/test_update_manifest.py`

**Interfaces:**
- Consumes: Python standard-library `dataclasses`, `enum`, `json`, `re`, and
  `urllib.parse`.
- Produces:
  - `ArtifactKind`
  - `UpdateChannel`
  - `UpdatePhase`
  - `UpdateErrorKind`
  - `ArtifactSpec`
  - `ReleaseManifest`
  - `UpdatePlan`
  - `OperationRecord`
  - `OperationStatus`
  - `UpdateFailure`
  - `UpdateCommandResult`
  - `UpdateAdminSnapshot`
  - `parse_release_manifest(raw: bytes) -> ReleaseManifest`
  - `validate_release_compatibility(manifest, platform, config_schema,
    current_db_schema, current_sequence) -> list[str]`

- [ ] **Step 1: Write strict parser tests**

Create tests with a local helper that emits this exact minimal schema:

```python
def valid_manifest_dict() -> dict[str, object]:
    return {
        "schema_version": 1,
        "release_id": "ailen-0.4.1-beta.1",
        "version": "0.4.1-beta.1",
        "sequence": 401001,
        "channel": "beta",
        "platforms": ["linux-amd64"],
        "config_schema_min": 1,
        "config_schema_max": 1,
        "migration_from_db_schema_min": 4,
        "migration_from_db_schema_max": 4,
        "db_schema_after": 4,
        "rollback_db_schema_min": 4,
        "rollback_db_schema_max": 4,
        "release_notes": "Synthetic beta fixture for updater tests.",
        "artifacts": [{
            "artifact_id": "ailen-core-linux-amd64-0.4.1-beta.1",
            "kind": "release",
            "url": "https://updates.example.invalid/artifacts/core.tar.gz",
            "sha256": "a" * 64,
            "size_bytes": 1024,
            "expanded_size_bytes": 4096,
            "platform": "linux-amd64",
            "media_type": "application/gzip",
        }],
    }
```

Assert acceptance of the valid document and rejection of:

- raw input over 1 MiB;
- duplicate JSON object keys;
- unknown `schema_version`;
- unknown top-level and artifact keys;
- non-positive `sequence`/`size_bytes`/`expanded_size_bytes`;
- invalid IDs, hashes, channels, platforms, and media types;
- release notes whose UTF-8 representation exceeds 8 KiB or contains NUL/control
  characters other than newline and tab;
- HTTP, credential-bearing, fragment-bearing, or malformed URLs;
- an empty artifact list;
- duplicate artifact IDs or duplicate hashes with conflicting metadata;
- rollback schema bounds that do not include `db_schema_after`;
- a release whose platform/config schema/current sequence are incompatible.

Use an explicit duplicate-key byte string rather than a Python dict:

```python
raw = b'{"schema_version":1,"schema_version":1}'
with pytest.raises(UpdateManifestError, match="duplicate key"):
    parse_release_manifest(raw)
```

- [ ] **Step 2: Run the new parser test and verify the expected failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_manifest.py -q
```

Expected: collection fails because `ailen.updates` does not exist.

- [ ] **Step 3: Implement pure contracts**

Define frozen DTOs with no path or I/O behavior:

```python
class ArtifactKind(StrEnum):
    RELEASE = "release"
    MODEL = "model"
    VOICE = "voice"
    FACEPACK = "facepack"


class UpdateChannel(StrEnum):
    NIGHTLY = "nightly"
    BETA = "beta"
    STABLE = "stable"


class UpdateErrorKind(StrEnum):
    INVALID_MANIFEST = "invalid_manifest"
    SIGNATURE_INVALID = "signature_invalid"
    SIGNATURE_UNAVAILABLE = "signature_unavailable"
    INCOMPATIBLE = "incompatible"
    NETWORK = "network"
    INTEGRITY = "integrity"
    INSUFFICIENT_DISK = "insufficient_disk"
    CANCELLED = "cancelled"
    ACTIVATION = "activation"
    ROLLBACK_FAILED = "rollback_failed"
    RECOVERY_REQUIRED = "recovery_required"
    INTERNAL = "internal"


class UpdatePhase(StrEnum):
    IDLE = "idle"
    CHECKING = "checking"
    PLANNED = "planned"
    DOWNLOADING = "downloading"
    VERIFIED = "verified"
    PREPARED = "prepared"
    ACTIVATING = "activating"
    PROBATION = "probation"
    ACTIVE = "active"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_id: str
    kind: ArtifactKind
    url: str
    sha256: str
    size_bytes: int
    expanded_size_bytes: int
    platform: str
    media_type: str


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    release_id: str
    version: str
    sequence: int
    channel: UpdateChannel
    platforms: tuple[str, ...]
    config_schema_min: int
    config_schema_max: int
    migration_from_db_schema_min: int
    migration_from_db_schema_max: int
    db_schema_after: int
    rollback_db_schema_min: int
    rollback_db_schema_max: int
    artifacts: tuple[ArtifactSpec, ...]
    release_notes: str


@dataclass(frozen=True)
class UpdatePlan:
    release_id: str
    version: str
    sequence: int
    artifacts: tuple[ArtifactSpec, ...]
    total_bytes: int
    reason_codes: tuple[str, ...]
    approval_required: bool = True


@dataclass(frozen=True)
class OperationRecord:
    schema_version: int
    operation_id: str
    phase: UpdatePhase
    release_id: str
    version: str
    sequence: int
    artifact_hashes: tuple[str, ...]
    downloaded_bytes: int
    total_bytes: int
    error_kind: UpdateErrorKind | None
    error_message: str
    started_at: str
    updated_at: str


@dataclass(frozen=True)
class OperationStatus:
    operation_id: str
    phase: UpdatePhase
    release_id: str
    downloaded_bytes: int
    total_bytes: int
    error_kind: UpdateErrorKind | None
    error_message: str
    started_at: str
    updated_at: str


@dataclass(frozen=True)
class UpdateCommandResult:
    ok: bool
    code: str
    message: str
    operation_id: str = ""
    approval_token: str = ""


@dataclass(frozen=True)
class UpdateAdminSnapshot:
    availability: str
    mode: str
    channel: UpdateChannel
    installed_version: str
    effective_version: str
    candidate_version: str
    release_notes: str
    operation: OperationStatus | None
    rollback_available: bool
    detail: str


class UpdateFailure(RuntimeError):
    def __init__(
        self,
        kind: UpdateErrorKind,
        message: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.public_message = message
        self.retry_after_seconds = retry_after_seconds


class UpdateManifestError(UpdateFailure):
    pass
```

`UpdateFailure.public_message` never contains an exception repr, local path,
URL credentials, response body, or OpenSSL stderr.

- [ ] **Step 4: Implement bounded strict JSON parsing**

Use `object_pairs_hook` to reject duplicate keys before dataclass construction.
Use exact allowlists for schema version 1. Validate URLs with
`urllib.parse.urlsplit`; require scheme `https`, a hostname, no username,
password, or fragment. Validate SHA-256 with `^[0-9a-f]{64}$` and identifiers
with `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.

`validate_release_compatibility()` takes these explicit parameters:

```python
def validate_release_compatibility(
    manifest: ReleaseManifest,
    *,
    platform: str,
    config_schema: int,
    current_db_schema: int,
    current_sequence: int,
) -> list[str]:
    reasons: list[str] = []
    if platform not in manifest.platforms:
        reasons.append("PLATFORM_UNSUPPORTED")
    if not manifest.config_schema_min <= config_schema <= manifest.config_schema_max:
        reasons.append("CONFIG_SCHEMA_UNSUPPORTED")
    if not (
        manifest.migration_from_db_schema_min
        <= current_db_schema
        <= manifest.migration_from_db_schema_max
    ):
        reasons.append("DB_MIGRATION_SOURCE_UNSUPPORTED")
    if not (
        manifest.rollback_db_schema_min
        <= manifest.db_schema_after
        <= manifest.rollback_db_schema_max
    ):
        reasons.append("ROLLBACK_DB_SCHEMA_UNSUPPORTED")
    if manifest.sequence <= current_sequence:
        reasons.append("RELEASE_NOT_NEWER")
    return reasons
```

Return stable reason codes such as `PLATFORM_UNSUPPORTED`,
`CONFIG_SCHEMA_UNSUPPORTED`, `ROLLBACK_DB_SCHEMA_UNSUPPORTED`, and
`RELEASE_NOT_NEWER`; do not return prose-only decisions.

- [ ] **Step 5: Run parser tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_manifest.py -q
```

Expected: all manifest tests pass.

- [ ] **Step 6: Review this task's diff**

Run:

```bash
git diff --check -- src/ailen/updates tests/unit/test_update_manifest.py
.venv/bin/ruff check src/ailen/updates tests/unit/test_update_manifest.py
.venv/bin/mypy src/ailen/updates
```

Expected: clean. Do not commit.

---

### Task 2: Ed25519 manifest trust boundary

**Files:**
- Create: `src/ailen/updates/signatures.py`
- Create: `src/ailen/updates/source.py`
- Modify: `src/ailen/updates/manifest.py`
- Test: `tests/unit/test_update_signatures.py`
- Test: `tests/unit/test_update_source.py`

**Interfaces:**
- Consumes: `ReleaseManifest`, `parse_release_manifest`, and exact manifest
  bytes from Task 1.
- Produces:
  - `SignatureVerifier.verify(manifest_path: Path, signature_path: Path,
    public_key_path: Path) -> bytes`
  - `OpenSslEd25519Verifier`
  - `UpdateSignatureError`
  - `VerifiedManifestLoader.load(manifest_path: Path, signature_path: Path,
    public_key_path: Path) -> ReleaseManifest`
  - `ByteFetcher.fetch(url: str, max_bytes: int) -> bytes`
  - `HttpsReleaseSource.fetch(channel: UpdateChannel) -> ReleaseManifest`

- [ ] **Step 1: Write signature tests with non-production ephemeral keys**

Test a fake verifier for pure unit behavior and an OpenSSL integration test
guarded by `shutil.which("openssl")`. Generate an ephemeral Ed25519 key under
`tmp_path`, sign exact manifest bytes, and verify that:

- valid bytes/signature/key load successfully;
- one changed byte fails closed;
- an empty or non-64-byte signature fails;
- missing/broken public key fails with `SIGNATURE_INVALID`;
- verifier timeout is classified `SIGNATURE_UNAVAILABLE`;
- the exception message does not expose absolute paths or OpenSSL stderr.

Use argument vectors, never `shell=True`. Production opens all three inputs with
`O_NOFOLLOW`, passes those descriptors through `/proc/self/fd` and `pass_fds`,
and parses only the exact manifest bytes returned by the verifier. The test key
fixture is explicitly mode `0644`:

```python
key_fd_path = f"/proc/self/fd/{key_fd}"
manifest_fd_path = f"/proc/self/fd/{manifest_fd}"
signature_fd_path = f"/proc/self/fd/{signature_fd}"
subprocess.run(
    ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", key_fd_path,
     "-rawin", "-in", manifest_fd_path, "-sigfile", signature_fd_path],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.PIPE,
    timeout=3.0,
    check=False,
    pass_fds=(manifest_fd, signature_fd, key_fd),
)
```

- [ ] **Step 2: Run the signature tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_signatures.py -q
```

Expected: import or assertion failure because the verifier is absent.

- [ ] **Step 3: Implement the verifier protocol and OpenSSL adapter**

`OpenSslEd25519Verifier` must:

- resolve `openssl` once through an injected binary path or `shutil.which`;
- require regular, non-symlink manifest/signature/key files;
- require owner/root controlled, non-group/world-writable public-key permissions
  by default; Lab tests may explicitly disable this only for a negative fixture;
- cap manifest at 1 MiB and signature at 64 bytes before spawning;
- call exactly `openssl pkeyutl -verify -pubin -inkey KEY -rawin -in
  MANIFEST -sigfile SIGNATURE` as an argument vector;
- set stdin to `DEVNULL`, timeout to 3 seconds, and never log stderr;
- return the exact verified manifest bytes on success and raise typed
  `UpdateSignatureError` otherwise. Compare manifest/signature/key snapshots
  before and after OpenSSL to fail closed on mutation.

Define `UpdateSignatureError` as an `UpdateFailure` subclass whose constructor
accepts only `SIGNATURE_INVALID` or `SIGNATURE_UNAVAILABLE`.

- [ ] **Step 4: Verify before parsing**

Implement:

```python
class SignatureVerifier(Protocol):
    def verify(
        self,
        manifest_path: Path,
        signature_path: Path,
        public_key_path: Path,
    ) -> bytes:
        raise NotImplementedError


class VerifiedManifestLoader:
    def __init__(self, verifier: SignatureVerifier) -> None:
        self._verifier = verifier

    def load(
        self,
        manifest_path: Path,
        signature_path: Path,
        public_key_path: Path,
    ) -> ReleaseManifest:
        verified_bytes = self._verifier.verify(
            manifest_path, signature_path, public_key_path
        )
        return parse_release_manifest(verified_bytes)
```

Do not parse or act on unverified fields before signature success.

- [ ] **Step 5: Implement and test the bounded HTTPS release source**

Define the injected byte boundary exactly:

```python
class ByteFetcher(Protocol):
    def fetch(self, url: str, *, max_bytes: int) -> bytes:
        raise NotImplementedError
```

`HttpsReleaseSource` receives configured manifest URL, signature URL, public-key
path, a `VerifiedManifestLoader`, and an injected `ByteFetcher`. The production
fetcher requires HTTPS, follows only HTTPS redirects, caps manifest bytes at
1 MiB and signature bytes at exactly 64 bytes, writes both to an injected
staging directory with mode `0600`, and calls the loader. It then requires the
signed manifest channel to equal the requested channel.

Tests use an in-memory `ByteFetcher`; they do not weaken the production URL
policy or use Internet. Assert size caps, redirect downgrade rejection, channel
mismatch rejection, verify-before-parse ordering, cleanup of failed staged
bytes, and public errors without URL/query/response content.

- [ ] **Step 6: Run focused tests and static gates**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_manifest.py tests/unit/test_update_signatures.py tests/unit/test_update_source.py -q
.venv/bin/ruff check src/ailen/updates tests/unit/test_update_signatures.py tests/unit/test_update_source.py
.venv/bin/mypy src/ailen/updates
git diff --check -- src/ailen/updates tests/unit/test_update_signatures.py tests/unit/test_update_source.py
```

Expected: clean. Do not commit.

---

### Task 3: Content-addressed artifact store

**Files:**
- Create: `src/ailen/updates/artifact_store.py`
- Test: `tests/unit/test_update_artifact_store.py`

**Interfaces:**
- Consumes: `ArtifactSpec` from Task 1.
- Produces:
  - `ContentAddressedArtifactStore`
  - `stage_path(operation_id: str) -> Path`
  - `commit(staged_path: Path, spec: ArtifactSpec) -> Path`
  - `object_path(sha256: str) -> Path`
  - `remove(sha256: str, protected: frozenset[str]) -> bool`

- [ ] **Step 1: Write store safety and integrity tests**

Cover:

- digest and operation-ID traversal rejection;
- deterministic `<root>/objects/<first-two>/<sha256>` placement;
- staging under `<root>/staging/<operation-id>.part` only;
- exact size and SHA-256 validation;
- deduplication when an existing object is valid;
- failure when an existing object is corrupt;
- read-only object mode after commit;
- staged file fsync and atomic same-filesystem replace;
- protected active/rollback digest removal refusal;
- symlink staging/object rejection;
- no deletion outside the injected root.

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_artifact_store.py -q
```

Expected: missing module/import failure.

- [ ] **Step 3: Implement the immutable store**

Validate IDs before constructing paths. Resolve the store root once and use
`Path.is_relative_to(root)` after resolving only parent directories; reject
symlinks with `lstat()` rather than following them. Stream SHA-256 in 64 KiB
chunks, compare with `hmac.compare_digest`, call `os.fsync()` on file and parent
directory, then set object mode `0444` in Lab simulation.

Return the existing object only after rechecking exact size and hash. Never name
an object with a URL basename or caller-provided relative path.

- [ ] **Step 4: Run tests and gates**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_artifact_store.py -q
.venv/bin/ruff check src/ailen/updates/artifact_store.py tests/unit/test_update_artifact_store.py
.venv/bin/mypy src/ailen/updates/artifact_store.py
git diff --check -- src/ailen/updates/artifact_store.py tests/unit/test_update_artifact_store.py
```

Expected: clean. Do not commit.

---

### Task 4: Bounded HTTPS download with honest resume and cancellation

**Files:**
- Create: `src/ailen/updates/downloader.py`
- Test: `tests/unit/test_update_downloader.py`

**Interfaces:**
- Consumes: `ArtifactSpec` and `ContentAddressedArtifactStore`.
- Produces:
  - `DownloadProgress(downloaded_bytes, total_bytes)`
  - `UrlPolicy.validate(url: str) -> None`
  - `HttpsArtifactDownloader.download(spec: ArtifactSpec, operation_id: str,
    cancellation: CancellationToken, on_progress: Callable[[DownloadProgress],
    None] | None = None) -> Path`
  - `CancellationToken.cancel()` / `CancellationToken.cancelled`

Define the small value and cancellation types in `downloader.py`:

```python
@dataclass(frozen=True)
class DownloadProgress:
    downloaded_bytes: int
    total_bytes: int


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class UrlPolicy(Protocol):
    def validate(self, url: str) -> None:
        raise NotImplementedError
```

The production implementation is `HttpsUrlPolicy`: it requires `https`, a
hostname, and no userinfo or fragment for the initial URL and every redirect.
The loopback-only test policy accepts `http://127.0.0.1:<ephemeral-port>` and
rejects every non-loopback host.

- [ ] **Step 1: Build a local deterministic HTTP test server**

Inside the test file, run `ThreadingHTTPServer` on loopback with handlers for:

- full `200` response with `Content-Length` and `ETag`;
- valid `206` with matching `Content-Range`;
- server ignoring `Range` and returning `200`;
- incorrect `Content-Length`;
- oversized body;
- changed ETag;
- `416` range rejection;
- slow chunks for cancellation.

Inject a URL-policy object that allows loopback HTTP only in tests. Production
policy remains HTTPS-only and rejects redirects to HTTP.

- [ ] **Step 2: Write download behavior tests**

Assert:

- a fresh download commits only after size/hash success;
- valid partial metadata resumes with `Range` and `If-Range`;
- a `200` response to a resume request truncates and restarts instead of
  appending;
- mismatched ETag discards the partial and restarts;
- cancellation leaves a resumable staged part and content-free metadata;
- hash/size/redirect failure never creates a CAS object;
- progress is monotonic and callback exceptions cannot corrupt the operation;
- response bodies and URLs do not enter public errors.

- [ ] **Step 3: Run the tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_downloader.py -q
```

Expected: missing downloader symbols.

- [ ] **Step 4: Implement resume metadata and streaming**

Persist this bounded metadata beside the part via atomic replace:

```json
{
  "schema_version": 1,
  "artifact_id": "ailen-core-linux-amd64-0.4.1-beta.1",
  "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "size_bytes": 1024,
  "downloaded_bytes": 512,
  "etag": "test-etag"
}
```

Do not persist query strings or credentials. The actual URL remains in the
verified manifest held by the operation.

Use 64 KiB reads, exact maximum size, a 10-second connect/read timeout default,
and check cancellation between chunks. Accept append only on `206` with a
matching range start and stable validator. On any ambiguity, restart from zero.
Install a custom `urllib.request.HTTPRedirectHandler` whose redirect method
calls `UrlPolicy.validate()` on every target before following it; the default
automatic redirect handler must not bypass HTTPS/userinfo/fragment policy.

- [ ] **Step 5: Run focused tests and gates**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_artifact_store.py tests/unit/test_update_downloader.py -q
.venv/bin/ruff check src/ailen/updates tests/unit/test_update_downloader.py
.venv/bin/mypy src/ailen/updates
git diff --check -- src/ailen/updates tests/unit/test_update_downloader.py
```

Expected: clean. Do not commit.

---

### Task 5: Atomic operation journal and single-worker update service

**Files:**
- Create: `src/ailen/updates/journal.py`
- Create: `src/ailen/updates/service.py`
- Test: `tests/unit/test_update_journal.py`
- Test: `tests/unit/test_update_service.py`

**Interfaces:**
- Consumes: manifest loader, compatibility validator, artifact downloader, and
  artifact store.
- Produces:
  - `OperationJournal.create/read/transition/list_incomplete`
  - `ReleaseSource.fetch(channel: UpdateChannel) -> ReleaseManifest`
  - `LocalUpdateService.check/plan/start_download/status/cancel/snapshot/close`
  - `DisabledUpdateService` returning stable `UNAVAILABLE` results without I/O
  - `UpdateAdminSnapshot` with redacted Web-safe fields.

Use these exact service-facing signatures:

```python
class OperationJournal:
    def create(self, record: OperationRecord) -> None:
        raise NotImplementedError

    def read(self, operation_id: str) -> OperationRecord:
        raise NotImplementedError

    def transition(
        self,
        operation_id: str,
        *,
        expected: frozenset[UpdatePhase],
        phase: UpdatePhase,
        downloaded_bytes: int | None = None,
        error_kind: UpdateErrorKind | None = None,
        error_message: str = "",
    ) -> OperationRecord:
        raise NotImplementedError

    def list_incomplete(self) -> tuple[OperationRecord, ...]:
        raise NotImplementedError


class ReleaseSource(Protocol):
    def fetch(self, channel: UpdateChannel) -> ReleaseManifest:
        raise NotImplementedError


class LocalUpdateService:
    def check(self) -> UpdateCommandResult:
        raise NotImplementedError

    def plan(self, release_id: str) -> UpdateCommandResult:
        raise NotImplementedError

    def start_download(
        self, release_id: str, approval_token: str
    ) -> UpdateCommandResult:
        raise NotImplementedError

    def status(self, operation_id: str) -> OperationStatus:
        raise NotImplementedError

    def cancel(self, operation_id: str) -> UpdateCommandResult:
        raise NotImplementedError

    def snapshot(self) -> UpdateAdminSnapshot:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
```

The implementation fills these bodies in Step 5; this block fixes the contract
that Tasks 6-9 consume. `DisabledUpdateService` implements the same methods,
performs no I/O, and returns or raises only typed `UNAVAILABLE` results.

- [ ] **Step 1: Write journal state-machine tests**

Allowed transitions are explicit:

```text
IDLE -> CHECKING -> PLANNED -> DOWNLOADING -> VERIFIED -> PREPARED
PREPARED -> ACTIVATING -> PROBATION -> ACTIVE
ACTIVATING|PROBATION|ACTIVE -> ROLLING_BACK -> ROLLED_BACK
CHECKING|PLANNED|DOWNLOADING|VERIFIED|PREPARED -> CANCELLED
any nonterminal phase -> FAILED
```

Assert rejection of transition skips, unknown operations, duplicate operation
IDs, malformed journals, symlinks, absolute paths, and journal records over
64 KiB. Assert atomic temp-write/fsync/replace and recovery of an incomplete
operation after constructing a new service instance.

Journal JSON contains only IDs, versions, sequences, phase, byte counters,
timestamps, hashes, and typed error codes. It must not contain URLs, HTTP bodies,
prompts, credentials, exception reprs, or absolute paths.

Cancellation removes only operation-owned incomplete staging bytes when they
are not resumable. It never deletes a verified CAS object or an extracted
release directory. Those remain inactive and are reclaimed only by the future
explicit, protected garbage-collection operation required by the specification.

- [ ] **Step 2: Write service tests**

Use fakes for the source and downloader. Assert:

- `check()` verifies before exposing release metadata;
- incompatible release reason codes prevent planning;
- `plan()` records exact artifacts/bytes and requires explicit approval token;
- only one download operation can run at once;
- cancellation targets only the matching operation;
- callback/status polling is thread-safe;
- an interrupted `DOWNLOADING` journal is recoverable, while interrupted
  `ACTIVATING` transitions to `FAILED` with error kind `RECOVERY_REQUIRED` in
  this vertical;
- disabled service returns `UNAVAILABLE`, not a fabricated current version;
- public snapshot excludes local paths and raw exceptions.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_journal.py tests/unit/test_update_service.py -q
```

Expected: missing modules/symbols.

- [ ] **Step 4: Implement atomic journal**

Use `OperationRecord` DTOs and an injected clock/ID factory. Write JSON with
sorted keys into a same-directory temporary file opened with mode `0600`, flush,
fsync, `os.replace`, and fsync the directory. Parse with exact key allowlists.

- [ ] **Step 5: Implement the bounded service**

Use one `ThreadPoolExecutor(max_workers=1, thread_name_prefix="ailen-update")`.
Construct the executor lazily on the first approved long operation and expose a
`close()` method. Do not start workers during import, health, or page rendering.

An approval token is an in-memory, one-use random value tied to release ID,
sequence, artifact hashes, total bytes, and a five-minute expiry. Never store it
in the journal or URL.

Document `LocalUpdateService` as the update-specific implementation of the
unprivileged `ProvisioningService` planning/status boundary named in the
approved specification. It is not the future privileged `ailen-updaterd`.

- [ ] **Step 6: Run focused tests and gates**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_journal.py tests/unit/test_update_service.py -q
.venv/bin/ruff check src/ailen/updates tests/unit/test_update_journal.py tests/unit/test_update_service.py
.venv/bin/mypy src/ailen/updates
git diff --check -- src/ailen/updates tests/unit/test_update_journal.py tests/unit/test_update_service.py
```

Expected: clean. Do not commit.

---

### Task 6: Safe release preparation and simulated atomic activation

**Files:**
- Create: `src/ailen/updates/activation.py`
- Modify: `src/ailen/updates/service.py`
- Test: `tests/unit/test_update_activation.py`
- Modify: `tests/unit/test_update_service.py`

**Interfaces:**
- Consumes: verified release artifact, `ReleaseManifest`, operation journal.
- Produces:
  - `SafeReleaseExtractor.prepare(artifact_path: Path, manifest:
    ReleaseManifest, spec: ArtifactSpec, paths: AppliancePaths) -> PreparedRelease`
  - `PreflightGate.check(release_dir: Path) -> HealthGateResult`
  - `ServiceController.stop() -> None`
  - `ServiceController.start(release_dir: Path) -> None`
  - `HealthGate.wait_healthy(timeout_seconds) -> HealthGateResult`
  - `ReleaseActivator.activate(prepared: PreparedRelease, operation_id: str,
    current_db_schema: int) -> ActivationResult`
  - `ReleaseActivator.rollback(operation_id: str) -> RollbackResult`
  - `LocalUpdateService.activate(operation_id: str) -> UpdateCommandResult`
  - `LocalUpdateService.rollback() -> UpdateCommandResult`

- [ ] **Step 1: Write malicious archive tests**

Generate tar fixtures under `tmp_path` and reject:

- absolute and `..` paths;
- symlinks, hard links, devices, FIFOs, sockets, and sparse surprises;
- duplicate normalized member paths;
- more than 10,000 members;
- expanded size greater than the manifest-declared maximum;
- files whose extracted parent resolves outside the release directory.

Accept only directories and regular files, applying conservative modes and
never preserving owner, group, setuid, setgid, or sticky bits from the archive.

- [ ] **Step 2: Write activation/rollback tests**

Using only an injected temporary appliance root, assert:

- release extracts into `releases/<version>.staging` then atomically renames;
- preflight failure leaves `current` unchanged;
- a temporary symlink is atomically replaced into `current`;
- service restart plus healthy probation keeps the new release;
- unhealthy probation restores the previous symlink and restarts it;
- rollback-compatible DB bounds are checked before switching;
- incompatible DB schema blocks activation before service stop;
- no down-migration or database snapshot restore is attempted;
- existing unrelated release/data paths are untouched;
- repeated activation and rollback are idempotent.

In `test_update_service.py`, inject a fake `ReleaseActivator` and assert that
`LocalUpdateService.activate()` accepts only a matching `PREPARED` operation,
that `rollback()` delegates once to the activator, and that both methods project
typed/redacted results while preserving journal transitions.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_activation.py -q
```

Expected: missing activation module.

- [ ] **Step 4: Implement safe extraction and path policy**

Inject this boundary instead of hardcoding system paths:

```python
@dataclass(frozen=True)
class AppliancePaths:
    install_root: Path
    state_root: Path

    @property
    def releases_dir(self) -> Path:
        return self.install_root / "releases"

    @property
    def current_link(self) -> Path:
        return self.install_root / "current"

    @property
    def data_dir(self) -> Path:
        return self.state_root

    def validate(self) -> None:
        install = self.install_root.resolve(strict=False)
        state = self.state_root.resolve(strict=False)
        home = Path.home().resolve(strict=False)
        if not install.is_absolute() or not state.is_absolute():
            raise ValueError("update roots must be absolute")
        if install in {Path("/"), home} or state in {Path("/"), home}:
            raise ValueError("broad update root refused")
        if install == state or install.is_relative_to(state) or state.is_relative_to(install):
            raise ValueError("install and state roots must be disjoint")


@dataclass(frozen=True)
class PreparedRelease:
    release_id: str
    version: str
    release_dir: Path
    previous_target: Path | None


@dataclass(frozen=True)
class HealthGateResult:
    healthy: bool
    reason_code: str
    detail: str


@dataclass(frozen=True)
class ActivationResult:
    ok: bool
    effective_version: str
    phase: UpdatePhase
    failure: UpdateFailure | None = None


@dataclass(frozen=True)
class RollbackResult:
    ok: bool
    effective_version: str
    phase: UpdatePhase
    failure: UpdateFailure | None = None


class PreflightGate(Protocol):
    def check(self, release_dir: Path) -> HealthGateResult:
        raise NotImplementedError


class ServiceController(Protocol):
    def stop(self) -> None:
        raise NotImplementedError

    def start(self, release_dir: Path) -> None:
        raise NotImplementedError


class HealthGate(Protocol):
    def wait_healthy(self, timeout_seconds: float) -> HealthGateResult:
        raise NotImplementedError
```

Production `SystemdServiceController` is not implemented in this vertical.
Provide only the protocol and deterministic fakes. The factory must label
activation `LAB_SIMULATION` until the appliance daemon vertical exists.

- [ ] **Step 5: Implement activation state machine**

Order operations exactly:

```text
verify prepared release
-> verify rollback-compatible DB bounds
-> preflight candidate without switching
-> stop fake/injected service controller
-> atomic current-link switch
-> start candidate
-> bounded health probation
-> ACTIVE, or restore link -> restart previous -> ROLLED_BACK
```

Record every phase transition in the operation journal. If restoration itself
fails, return `ROLLBACK_FAILED` and preserve both release directories and the
journal for recovery; do not attempt recursive cleanup.

Extend `LocalUpdateService` with the exact two methods declared above. The
service owns operation lookup, phase validation, and DTO projection; the
injected `ReleaseActivator` owns only extraction/symlink/service/health actions.
`DisabledUpdateService.activate()` and `.rollback()` return `UNAVAILABLE`
without constructing an activator or touching the filesystem.

- [ ] **Step 6: Run focused tests and gates**

Run:

```bash
.venv/bin/pytest tests/unit/test_update_activation.py tests/unit/test_update_service.py -q
.venv/bin/ruff check src/ailen/updates tests/unit/test_update_activation.py tests/unit/test_update_service.py
.venv/bin/mypy src/ailen/updates
git diff --check -- src/ailen/updates tests/unit/test_update_activation.py tests/unit/test_update_service.py
```

Expected: clean. Do not commit.

---

### Task 7: Configuration and honest update-service factory

**Files:**
- Modify: `src/ailen/core/config.py`
- Modify: `config/ailen.example.toml`
- Create: `src/ailen/updates/factory.py`
- Test: `tests/unit/test_update_factory.py`
- Modify: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `UpdatesConfig`, update service, store, loader, and activator.
- Produces: `build_update_service(config: AILENConfig, mode: str,
  paths: AppliancePaths) -> LocalUpdateService | DisabledUpdateService`.

- [ ] **Step 1: Write configuration tests**

Extend `UpdatesConfig` with exact fields:

```python
@dataclass
class UpdatesConfig:
    channel: str = "beta"
    auto_check: bool = False
    check_interval_hours: int = 24
    manifest_url: str = ""
    manifest_signature_url: str = ""
    trust_public_key_path: str = ""
    auto_install: bool = False
    maintenance_window: str = "03:00"
```

Assert strict channel, interval `1..168`, valid `HH:MM`, paired manifest/signature
URLs, HTTPS-only production URLs, and rejection of `auto_install=true` when
trust/source are incomplete. Do not expose `trust_public_key_path` or URLs as
editable generic Web settings in this vertical.

- [ ] **Step 2: Write factory truthfulness tests**

Assert:

- incomplete source/trust returns a disabled service with explicit reason;
- Lab Mode builds download/prepare support but labels activation simulation;
- Appliance Mode refuses real activation because `ailen-updaterd` is not yet
  implemented;
- construction performs no network request, OpenSSL call, directory creation,
  thread start, or system mutation;
- no configured path may resolve to repository root, `/`, or a home directory.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_config.py tests/unit/test_update_factory.py -q
```

Expected: assertions/imports fail before implementation.

- [ ] **Step 4: Implement config validation and factory**

Use the existing config parser/validator patterns. Do not add legacy aliases for
old update keys. The example config remains disabled and contains no real
release host or trust key:

```toml
[updates]
channel = "beta"
auto_check = false
check_interval_hours = 24
manifest_url = ""
manifest_signature_url = ""
trust_public_key_path = ""
auto_install = false
maintenance_window = "03:00"
```

- [ ] **Step 5: Run tests and gates**

Run:

```bash
.venv/bin/pytest tests/unit/test_config.py tests/unit/test_update_factory.py -q
.venv/bin/ruff check src/ailen/core/config.py src/ailen/updates/factory.py tests/unit/test_update_factory.py
.venv/bin/mypy src/ailen/core/config.py src/ailen/updates
git diff --check -- src/ailen/core/config.py config/ailen.example.toml src/ailen/updates tests/unit/test_update_factory.py
```

Expected: clean. Do not commit.

---

### Task 8: Authenticated backend and lightweight Updates page

**Files:**
- Modify: `src/ailen/web/services.py`
- Modify: `src/ailen/web/app.py`
- Modify: `src/ailen/web/templates/base.html`
- Create: `src/ailen/web/templates/updates.html`
- Modify: `src/ailen/cli.py`
- Create: `tests/web/test_updates_admin.py`
- Modify: `tests/web/test_http_smoke.py`

**Interfaces:**
- Consumes: `UpdateAdminService` from Task 5/7.
- Produces authenticated routes:
  - `GET /actualizaciones`
  - `POST /api/updates/check`
  - `POST /api/updates/plan`
  - `POST /api/updates/download`
  - `POST /api/updates/cancel`
  - `POST /api/updates/activate`
  - `POST /api/updates/rollback`
  - `GET /api/updates/status?operation_id=<id>`

- [ ] **Step 1: Write Web authorization and CSRF tests**

For every route assert:

- unauthenticated request redirects or returns `403` according to existing
  conventions;
- state-changing POST without valid CSRF returns `403`;
- invalid/unknown operation IDs return typed `400/404` without traceback;
- disabled service renders `UNAVAILABLE` and no activation buttons;
- Lab simulation renders `LAB_SIMULATION`, never `READY_FOR_APPLIANCE`;
- page contains selected channel, installed/effective version, operation phase,
  total bytes, progress, HTML-escaped release notes, restart/rollback
  availability, and public error code;
- page/JSON do not contain manifest URL, public-key path, artifact filesystem
  path, exception repr, prompt, or secret;
- a simulated browser disconnect/BrokenPipe does not cancel the update worker.

- [ ] **Step 2: Run Web tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/web/test_updates_admin.py tests/web/test_http_smoke.py -q
```

Expected: missing routes/service/template.

- [ ] **Step 3: Add the narrow Web service protocol and fake**

The Web contract exposes serializable DTOs only:

```python
class UpdateAdminService(Protocol):
    def snapshot(self) -> UpdateAdminSnapshot:
        raise NotImplementedError

    def check(self) -> UpdateCommandResult:
        raise NotImplementedError

    def plan(self, release_id: str) -> UpdateCommandResult:
        raise NotImplementedError

    def start_download(
        self, release_id: str, approval_token: str
    ) -> UpdateCommandResult:
        raise NotImplementedError

    def cancel(self, operation_id: str) -> UpdateCommandResult:
        raise NotImplementedError

    def activate(self, operation_id: str) -> UpdateCommandResult:
        raise NotImplementedError

    def rollback(self) -> UpdateCommandResult:
        raise NotImplementedError

    def status(self, operation_id: str) -> OperationStatus:
        raise NotImplementedError
```

`AILENWebApp.__init__` receives `updates: UpdateAdminService | None = None` and
uses an explicit disabled fake when absent, preserving current tests without
claiming availability.

- [ ] **Step 4: Implement routes and template**

Add `actualizaciones` to `_page()` navigation flags and to the Infrastructure
sidebar. The page uses existing CSS classes and plain JavaScript polling at no
faster than one request per second while an operation is active. Stop polling on
terminal phase or page unload.

Every state-changing POST handler uses `_check_csrf`, parses only explicit
fields, and delegates once to the service. The authenticated status GET accepts
only `operation_id` and performs no mutation. No handler imports `subprocess`,
`tarfile`, downloader, artifact store, or activation code.

- [ ] **Step 5: Wire the service in the existing Web CLI path**

In `cmd_web`, call `build_update_service()` with the current config and explicit
absolute Lab Mode paths derived as
`(Path("runtime/lab/update-simulation") / "install").resolve()` and
`(Path("runtime/lab/update-simulation") / "state").resolve()`. The ignored
directory is not created until an approved operation. Do not start update checks
during Web boot.

- [ ] **Step 6: Run Web tests and gates**

Run:

```bash
.venv/bin/pytest tests/web/test_updates_admin.py tests/web/test_http_smoke.py tests/web/test_app.py -q
.venv/bin/ruff check src/ailen/web src/ailen/cli.py tests/web/test_updates_admin.py
.venv/bin/mypy src/ailen/web src/ailen/updates src/ailen/cli.py
git diff --check -- src/ailen/web src/ailen/cli.py tests/web/test_updates_admin.py
```

Expected: clean. Do not commit.

---

### Task 9: End-to-end simulated signed update

**Files:**
- Create: `tests/integration/test_update_vertical.py`
- Modify production modules from Tasks 1-8 only when the integration test proves
  a concrete contract defect.

**Interfaces:**
- Consumes: all Vertical 1 production boundaries.
- Produces: a reproducible, no-network, no-system-mutation acceptance test.

- [ ] **Step 1: Write successful end-to-end test**

Under `tmp_path`:

1. build a tiny safe release tar containing `VERSION` and a health marker;
2. compute its exact size/SHA-256;
3. build exact manifest JSON;
4. generate a test-only Ed25519 key with OpenSSL;
5. sign exact manifest bytes;
6. load/verify/parse the manifest;
7. download through an injected loopback source;
8. commit to CAS;
9. prepare release;
10. switch a temporary `current` symlink;
11. pass fake health probation;
12. assert `ACTIVE`, exact version/hash, and no file outside the temp appliance
    root.

- [ ] **Step 2: Write failure/rollback end-to-end test**

Activate release A, then attempt signed release B with an unhealthy fake. Assert:

- B reaches probation but not active;
- `current` returns to A;
- A and B artifacts/releases remain intact;
- journal ends `ROLLED_BACK` with typed gate failure;
- no database restore/down-migration function was called;
- Web snapshot reports effective A and attempted B without leaking paths.

- [ ] **Step 3: Write interrupted-download recovery test**

Cancel halfway, construct a fresh service over the same injected store/journal,
resume with matching ETag/range, and assert the final CAS object equals the
expected hash without duplicate bytes.

- [ ] **Step 4: Run the integration test**

Run:

```bash
.venv/bin/pytest tests/integration/test_update_vertical.py -q
```

Expected: all three scenarios pass without Internet, `/opt`, systemd, or live
database access.

- [ ] **Step 5: Run the complete update/Web focal suite**

Run:

```bash
.venv/bin/pytest \
  tests/unit/test_update_manifest.py \
  tests/unit/test_update_signatures.py \
  tests/unit/test_update_source.py \
  tests/unit/test_update_artifact_store.py \
  tests/unit/test_update_downloader.py \
  tests/unit/test_update_journal.py \
  tests/unit/test_update_service.py \
  tests/unit/test_update_activation.py \
  tests/unit/test_update_factory.py \
  tests/web/test_updates_admin.py \
  tests/web/test_http_smoke.py \
  tests/integration/test_update_vertical.py -q
```

Expected: clean. Do not commit.

---

### Task 10: Contracts, ADR, documentation, and complete gates

**Files:**
- Modify: `docs/architecture/MODULE_CONTRACTS.md`
- Modify: `docs/deployment/DEPLOYMENT_PLAN.md`
- Create: `docs/architecture/adr/ADR-013-signed-provisioning-and-recoverable-updates.md`
- Modify: `docs/architecture/adr/README.md`
- Modify: `ROADMAP.md`
- Modify: `TASKS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/memory/CURRENT_STATE.md`
- Modify: `docs/memory/RECENT_DECISIONS.md`

**Interfaces:**
- Consumes: verified implementation and actual test/gate output.
- Produces: canonical documentation that distinguishes Vertical 1 simulation
  from future appliance activation.

- [ ] **Step 1: Update canonical updater contract**

Replace the old `check/prepare/activate/rollback` sketch with the exact
operation-oriented interface implemented in Task 5. State that Web consumes
`UpdateAdminService`, while the future privileged daemon implements the narrow
activation boundary.

- [ ] **Step 2: Write ADR-013 from implemented facts**

Record:

- signed exact manifest bytes and signed artifact hashes;
- OpenSSL Ed25519 public-key verification;
- content-addressed storage;
- operation journal and one-worker policy;
- Lab simulation versus appliance mutation boundary;
- backward-compatible migration requirement;
- atomic switch and health rollback behavior;
- rejected alternatives: unsigned hash-only manifests, Web shell operations,
  in-place overwrite, automatic down-migrations, and model weights in wheel.

- [ ] **Step 3: Align deployment paths and status documents**

Use `/var/lib/ailen/artifacts/<sha256>/` and `/var/lib/ailen/provisioning/` in
deployment docs. Mark `ailen-updaterd`, systemd activation, signing pipeline,
offline-bundle CLI, power-loss testing, and physical appliance rollback as not
implemented by Vertical 1. Do not claim a release or supported 4/8 GB profile.

- [ ] **Step 4: Run full automated gates**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
git diff --check
```

Expected: complete suite, Ruff, mypy, and diff-check pass. Record the actual
test count; do not reuse the previous 767 baseline if it changed.

- [ ] **Step 5: Build and inspect the wheel**

Build without dependency downloads into a fresh ignored laboratory directory:

```bash
wheel_gate_dir="$(mktemp -d runtime/lab/wheel-gate.XXXXXX)"
.venv/bin/python -m build --wheel --no-isolation --outdir "$wheel_gate_dir"
wheel_path="$(find "$wheel_gate_dir" -maxdepth 1 -type f -name '*.whl' -print -quit)"
unzip -Z1 "$wheel_path" > "$wheel_gate_dir/wheel-files.txt"
```

Inspect the archive and fail the gate if this command finds any match:

```bash
rg -n '(^|/)raw_h3(/|$)|^runtime/|\.(gguf|safetensors|pt|facepack|mp4|wav|pcm|so|dll|pem|key|sig)$' "$wheel_gate_dir/wheel-files.txt"
```

Expected: no matches. This covers:

```text
*.gguf
*.safetensors
*.pt
*.facepack
*.mp4
*.wav
*.pcm
*.so
*.dll
raw_h3/
runtime/
*.pem
*.key
*.sig
```

`^runtime/` se refiere al directorio de artefactos Lab en la raíz del wheel;
`ailen/runtime/` es código Python productivo y debe permanecer incluido.

The Python updater modules and `updates.html` must be included.

```bash
rg -n '^ailen/updates/__init__\.py$|^ailen/web/templates/updates\.html$' "$wheel_gate_dir/wheel-files.txt"
```

Expected: both paths are present.

- [ ] **Step 6: Scan for accidental secrets and unsafe update behavior**

Scan only the Vertical 1 paths and print filenames, never matched values:

```bash
rg -l --hidden '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|[Aa]uthorization:[[:space:]]*[Bb]earer|api[_-]?key[[:space:]]*=|password[[:space:]]*=)' \
  src/ailen/updates src/ailen/web/app.py src/ailen/web/services.py \
  src/ailen/web/templates/updates.html src/ailen/cli.py \
  config/ailen.example.toml tests/unit/test_update_*.py \
  tests/web/test_updates_admin.py tests/integration/test_update_vertical.py
```

Expected: no production secret file. If a test fixture filename is reported,
inspect it manually without printing the matching line and confirm it contains
only an obviously synthetic value.

Scan Web additions for forbidden execution/mutation primitives and insecure
production URLs:

```bash
git diff --unified=0 -- src/ailen/web/app.py src/ailen/web/services.py src/ailen/web/templates/updates.html | rg -n '^\+.*(subprocess|shell=True|/opt/ailen|/var/lib/ailen|http://)'
```

Expected: no matches. Also list prohibited binary/key artifacts by filename:

```bash
find src tests config -type f \( -name '*.pem' -o -name '*.key' -o -name '*.sig' -o -name '*.gguf' -o -name '*.facepack' -o -name '*.mp4' -o -name '*.wav' -o -name '*.pcm' \) -print
```

Inspect any pre-existing repository fixture separately; Vertical 1 must add
none of them.

- [ ] **Step 7: Review final diff and stop**

Review only the files in this vertical plus pre-existing overlapping user edits.
Report files changed, tests/gates, simulated activation evidence, and remaining
appliance work. Do not commit or push.

---

## Vertical 1 completion boundary

This plan is complete only when a signed tiny synthetic release can be verified,
downloaded, stored, prepared, activated, health-checked, and rolled back entirely
inside an injected temporary appliance root, and the authenticated Web page
reports that lifecycle honestly.

It does **not** authorize or claim:

- writes to real appliance paths;
- a production signing pipeline;
- `ailen-updaterd` or systemd service installation;
- automatic stable updates;
- model/voice provisioning;
- Chatterbox service deployment;
- LAN pairing;
- 4 GB/8 GB hardware support.

Those are separate plans derived from the same approved specification after the
Vertical 1 contracts are proven.
