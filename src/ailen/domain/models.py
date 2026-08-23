"""Domain models for AILEN."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from ailen.domain.enums import (
    AssistantState,
    DeviceProfile,
    ErrorCode,
    EventType,
    PrivacyLevel,
    ServiceStatus,
    SocialMode,
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


@dataclass
class RuntimeState:
    """Observable runtime state for health checks and dashboards.
    
    Safe to expose publicly without secrets.
    """
    version: str
    node_id: str
    profile: DeviceProfile
    assistant_state: AssistantState = AssistantState.BOOTING
    uptime_seconds: float = 0.0
    internet_status: ServiceStatus = ServiceStatus.UNKNOWN
    lan_brain_status: ServiceStatus = ServiceStatus.DISABLED
    cloud_status: ServiceStatus = ServiceStatus.UNKNOWN
    camera_status: ServiceStatus = ServiceStatus.UNKNOWN
    microphone_status: ServiceStatus = ServiceStatus.UNKNOWN
    speaker_status: ServiceStatus = ServiceStatus.UNKNOWN
    memory_status: ServiceStatus = ServiceStatus.UNKNOWN
    last_error_code: ErrorCode | None = None
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Convert runtime state to serializable dictionary."""
        data = asdict(self)
        data["profile"] = self.profile.value
        data["assistant_state"] = self.assistant_state.value
        data["internet_status"] = self.internet_status.value
        data["lan_brain_status"] = self.lan_brain_status.value
        data["cloud_status"] = self.cloud_status.value
        data["camera_status"] = self.camera_status.value
        data["microphone_status"] = self.microphone_status.value
        data["speaker_status"] = self.speaker_status.value
        data["memory_status"] = self.memory_status.value
        if self.last_error_code:
            data["last_error_code"] = self.last_error_code.value
        return data


@dataclass
class AssistantIdentity:
    """Core identity configuration. Independent from LLM models."""
    identity_id: str
    name: str
    created_at: str = field(default_factory=utc_now_iso)
    personality_seed: str = "ailen-seed-default"
    active_personality_version: int = 1
    display_name: str | None = None

    @property
    def effective_display_name(self) -> str:
        """Return display_name if set, otherwise fallback to internal identity name."""
        return self.display_name if self.display_name is not None else self.name


@dataclass
class ConversationSession:
    """Active or historical conversation session."""
    session_id: str
    started_at: str = field(default_factory=utc_now_iso)
    ended_at: str | None = None
    mode: SocialMode = SocialMode.WORKSHOP
    participant_hint: str | None = None
    source_node_id: str = "node-local"


@dataclass
class Message:
    """A conversational message inside a session."""
    message_id: str
    session_id: str
    role: str  # "user", "assistant", "system", "tool"
    content: str
    mode: SocialMode = SocialMode.WORKSHOP
    created_at: str = field(default_factory=utc_now_iso)
    token_count: int | None = None


@dataclass
class MemoryItem:
    """A persistent memory entry."""
    memory_id: str
    category: str
    content: str
    importance: float = 1.0  # 0.0 to 5.0
    scope: PrivacyLevel = PrivacyLevel.PRIVATE
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None


@dataclass
class NoteItem:
    """A persisted user note."""
    note_id: str
    content: str
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class BusinessFact:
    """Business knowledge administered by the owner."""
    fact_id: str
    key: str
    category: str
    value: str
    is_public: bool = True
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class PreferenceItem:
    """Learned or explicit preference."""
    pref_id: str
    category: str
    key: str
    value: str
    confidence: float = 1.0
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class ToolEvent:
    """Audit record for a tool execution."""
    event_id: str
    session_id: str | None
    tool_name: str
    arguments_redacted: str
    result_summary: str
    success: bool
    latency_ms: float
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class AiUsageRecord:
    """Tracked AI token usage and cost."""
    usage_id: str
    session_id: str | None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    latency_ms: float
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class SystemEventRecord:
    """Audit record for operational system events."""
    event_id: str
    event_type: str
    severity: str  # INFO, WARNING, ERROR, CRITICAL
    component: str
    message: str
    payload_json: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class CoreEvent:
    """Internal event published across core components."""
    event_id: str
    event_type: EventType
    timestamp: str = field(default_factory=utc_now_iso)
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "core"
    correlation_id: str | None = None


@dataclass
class HealthReport:
    """Aggregated health report."""
    status: ServiceStatus
    components: dict[str, ServiceStatus] = field(default_factory=dict)
    checked_at: str = field(default_factory=utc_now_iso)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CpuInfo:
    """CPU hardware information."""
    model: str = "Unknown"
    arch: str = "Unknown"
    cores_physical: int = 1
    cores_logical: int = 1
    frequency_mhz: float | None = None


@dataclass
class MemoryInfo:
    """RAM information."""
    total_bytes: int = 0
    available_bytes: int = 0
    used_bytes: int = 0
    total_mb: float = 0.0
    available_mb: float = 0.0


@dataclass
class DiskInfo:
    """Disk storage information."""
    mount_point: str = "/"
    total_bytes: int = 0
    free_bytes: int = 0
    used_bytes: int = 0
    total_gb: float = 0.0
    free_gb: float = 0.0


@dataclass
class GpuInfo:
    """GPU / Accelerator information."""
    detected: bool = False
    name: str = "None"
    driver: str | None = None


@dataclass
class AudioDeviceInfo:
    """Audio input/output device info."""
    index: int
    name: str
    is_input: bool
    is_output: bool
    is_default: bool = False


@dataclass
class CameraInfo:
    """Video capture device info."""
    device_path: str
    name: str
    accessible: bool = False


@dataclass
class DisplayInfo:
    """Display device info."""
    connector: str
    connected: bool
    resolution: str | None = None


@dataclass
class NetworkInfo:
    """Network interface info."""
    interface: str
    is_up: bool
    ip_address: str | None = None


@dataclass
class OsInfo:
    """Operating system and kernel information."""
    system: str = "Linux"
    release: str = "Unknown"
    distribution: str = "Unknown"
    kernel_version: str = "Unknown"


@dataclass
class HardwareReport:
    """Complete hardware diagnostics report."""
    cpu: CpuInfo = field(default_factory=CpuInfo)
    memory: MemoryInfo = field(default_factory=MemoryInfo)
    disk: DiskInfo = field(default_factory=DiskInfo)
    gpu: GpuInfo = field(default_factory=GpuInfo)
    audio_inputs: list[AudioDeviceInfo] = field(default_factory=list)
    audio_outputs: list[AudioDeviceInfo] = field(default_factory=list)
    cameras: list[CameraInfo] = field(default_factory=list)
    displays: list[DisplayInfo] = field(default_factory=list)
    network: list[NetworkInfo] = field(default_factory=list)
    os: OsInfo = field(default_factory=OsInfo)
    recommended_profile: DeviceProfile = DeviceProfile.HYBRID
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Convert hardware report to dictionary."""
        data = asdict(self)
        data["recommended_profile"] = self.recommended_profile.value
        return data
