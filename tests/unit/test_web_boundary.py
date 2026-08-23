"""Unit tests for Web Search and Web Fetch boundaries and anti-SSRF protections."""

from ailen.domain.enums import ErrorCode
from ailen.tools.builtin.web_fetch import (
    ALLOWED_CONTENT_TYPES,
    DEFAULT_MAX_BYTES,
    WebFetchPolicy,
    WebFetchTool,
)
from ailen.tools.builtin.web_search import (
    FakeWebSearchProvider,
    UnconfiguredWebSearchProvider,
    WebSearchRequest,
    WebSearchResult,
    WebSearchTool,
)
from ailen.tools.contracts import ToolContext


def test_web_search_unconfigured_provider() -> None:
    provider = UnconfiguredWebSearchProvider()
    resp = provider.search(WebSearchRequest(query="test"))
    assert resp.success is False
    assert resp.status == "UNCONFIGURED"
    assert resp.cost_tier == "UNKNOWN"

    tool = WebSearchTool(provider=provider)
    result = tool.execute({"query": "Debian 13"}, ToolContext())
    assert result.success is False
    assert result.status_code == "UNCONFIGURED"
    assert "no está configurado" in result.message
    assert result.requires_llm_summary is False


def test_web_search_fake_provider() -> None:
    canned = {
        "python": [
            WebSearchResult(
                title="Python Programming",
                snippet="Python is an interpreted language.",
                url="https://python.org",
            )
        ]
    }
    provider = FakeWebSearchProvider(canned_results=canned)
    tool = WebSearchTool(provider=provider)

    result = tool.execute({"query": "python tips", "max_results": 1}, ToolContext())
    assert result.success is True
    assert result.status_code == "OK"
    assert result.data["count"] == 1
    assert result.data["results"][0]["title"] == "Python Programming"
    assert result.requires_llm_summary is True


def test_web_fetch_policy_ip_blocking() -> None:
    # Loopback
    assert WebFetchPolicy.is_ip_allowed("127.0.0.1")[0] is False
    assert WebFetchPolicy.is_ip_allowed("127.0.1.1")[0] is False
    assert WebFetchPolicy.is_ip_allowed("::1")[0] is False

    # Private networks (RFC1918)
    assert WebFetchPolicy.is_ip_allowed("10.0.0.1")[0] is False
    assert WebFetchPolicy.is_ip_allowed("172.16.0.1")[0] is False
    assert WebFetchPolicy.is_ip_allowed("192.168.1.1")[0] is False

    # Link local & Cloud metadata
    assert WebFetchPolicy.is_ip_allowed("169.254.169.254")[0] is False
    assert WebFetchPolicy.is_ip_allowed("169.254.1.1")[0] is False
    assert WebFetchPolicy.is_ip_allowed("fe80::1")[0] is False

    # Invalid / non-routable
    assert WebFetchPolicy.is_ip_allowed("0.0.0.0")[0] is False
    assert WebFetchPolicy.is_ip_allowed("256.256.256.256")[0] is False

    # Public routable IPs
    assert WebFetchPolicy.is_ip_allowed("8.8.8.8")[0] is True
    assert WebFetchPolicy.is_ip_allowed("1.1.1.1")[0] is True
    assert WebFetchPolicy.is_ip_allowed("93.184.216.34")[0] is True


def test_web_fetch_policy_validate_url_schemes_and_hosts() -> None:
    # Prohibited schemes
    assert WebFetchPolicy.validate_url("file:///etc/passwd")[0] is False
    assert WebFetchPolicy.validate_url("ftp://example.com/file")[0] is False
    assert WebFetchPolicy.validate_url("data:text/plain;base64,aGVsbG8=")[0] is False
    assert WebFetchPolicy.validate_url("javascript:alert(1)")[0] is False
    assert WebFetchPolicy.validate_url("gopher://example.com")[0] is False
    assert WebFetchPolicy.validate_url("http://example.com")[0] is False
    assert WebFetchPolicy.validate_url("https://user:pass@example.com/path")[0] is False

    # Prohibited hostnames
    assert WebFetchPolicy.validate_url("http://localhost:8080/admin")[0] is False
    assert WebFetchPolicy.validate_url("https://127.0.0.1:8000")[0] is False
    assert WebFetchPolicy.validate_url("http://metadata.google.internal/computeMetadata/v1/")[0] is False
    assert WebFetchPolicy.validate_url("https://192.168.0.1/status")[0] is False


def test_web_fetch_tool_blocks_ssrf() -> None:
    tool = WebFetchTool()
    res = tool.execute({"url": "http://127.0.0.1:8080/status"}, ToolContext())
    assert res.success is False
    assert res.status_code == "SSRF_BLOCKED"
    assert res.error_code == ErrorCode.TOOL_SSRF_BLOCKED


def test_web_fetch_tool_content_type_allowlist() -> None:
    assert "text/html" in ALLOWED_CONTENT_TYPES
    assert "application/json" in ALLOWED_CONTENT_TYPES
    assert "application/octet-stream" not in ALLOWED_CONTENT_TYPES
    assert "image/png" not in ALLOWED_CONTENT_TYPES
    assert "application/zip" not in ALLOWED_CONTENT_TYPES


def test_web_fetch_tool_max_bytes() -> None:
    tool = WebFetchTool(max_bytes=100)
    assert tool.max_bytes == 100
    assert DEFAULT_MAX_BYTES == 256 * 1024


def test_web_search_bounds_and_sanitizes_provider_output() -> None:
    provider = FakeWebSearchProvider(
        canned_results={
            "test": [
                WebSearchResult(
                    title="  " + ("T" * 400) + "  ",
                    snippet="S" * 2000,
                    url="javascript:alert(1)",
                    source="x" * 200,
                )
            ]
        }
    )
    tool = WebSearchTool(provider=provider)
    result = tool.execute({"query": "test", "max_results": 1}, ToolContext())
    assert result.success is True
    item = result.data["results"][0]
    assert len(item["title"]) <= 300
    assert len(item["snippet"]) <= 1200
    assert item["url"] == ""
    assert len(item["source"]) <= 120
