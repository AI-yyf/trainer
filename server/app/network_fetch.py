"""Controlled outbound HTTP fetching for Trainer-owned source acquisition.

The sidecar must not delegate URL fetching to the host resolver a second time
after it has made an admission decision.  This module resolves a host once,
rejects non-public targets, and connects the resulting vetted address directly.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 4
DEFAULT_MAX_RESOLVED_ADDRESSES = 8
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class ControlledFetchError(RuntimeError):
    """A stable, display-safe failure from the controlled fetch boundary."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ControlledFetchResponse:
    """A fully buffered successful HTTP response."""

    body: bytes
    final_url: str
    status: int
    headers: dict[str, str]
    fetched_at: str

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")


@dataclass(frozen=True, slots=True)
class _ResolvedAddress:
    family: int
    protocol: int
    sockaddr: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    request_target: str
    addresses: tuple[_ResolvedAddress, ...]


class ControlledHttpFetcher:
    """Fetch an HTTP(S) URL through a DNS-pinned, bounded transport."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_resolved_addresses: int = DEFAULT_MAX_RESOLVED_ADDRESSES,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        if max_resolved_addresses <= 0:
            raise ValueError("max_resolved_addresses must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self.max_resolved_addresses = max_resolved_addresses

    def fetch(
        self,
        url: str,
        *,
        network_enabled: bool,
        headers: Mapping[str, str] | None = None,
    ) -> ControlledFetchResponse:
        if not network_enabled:
            raise ControlledFetchError(
                "network_disabled",
                "Network source acquisition is disabled by Trainer configuration.",
            )

        current_url = str(url or "").strip()
        deadline = time.monotonic() + self.timeout_seconds
        for redirect_count in range(self.max_redirects + 1):
            self._remaining_timeout(deadline)
            target = self._resolve_target(current_url)
            status, response_headers, body = self._request_once(
                target,
                headers=headers,
                deadline=deadline,
            )
            if status not in _REDIRECT_STATUSES:
                return ControlledFetchResponse(
                    body=body,
                    final_url=target.url,
                    status=status,
                    headers=response_headers,
                    fetched_at=datetime.now(UTC).isoformat(),
                )

            location = response_headers.get("location", "").strip()
            if not location:
                raise ControlledFetchError("redirect_missing_location", "Redirect response did not include a Location header.")
            if redirect_count >= self.max_redirects:
                raise ControlledFetchError("redirect_limit", "URL redirect limit was reached.")
            current_url = urljoin(target.url, location)

        raise ControlledFetchError("redirect_limit", "URL redirect limit was reached.")

    def _resolve_target(self, url: str) -> _ResolvedTarget:
        try:
            parsed = urlsplit(str(url or "").strip())
        except ValueError as exc:
            raise ControlledFetchError("invalid_url", "URL is invalid.") from exc
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise ControlledFetchError("unsupported_scheme", "Only http and https URLs are allowed.")
        if parsed.username is not None or parsed.password is not None:
            raise ControlledFetchError("userinfo_not_allowed", "URL userinfo is not allowed.")

        raw_host = (parsed.hostname or "").strip().rstrip(".")
        if not raw_host:
            raise ControlledFetchError("missing_host", "URL host is missing.")
        try:
            host = raw_host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ControlledFetchError("invalid_host", "URL host is invalid.") from exc
        default_port = 443 if scheme == "https" else 80
        try:
            port = parsed.port or default_port
        except ValueError as exc:
            raise ControlledFetchError("invalid_port", "URL port is invalid.") from exc
        if not 1 <= port <= 65535:
            raise ControlledFetchError("invalid_port", "URL port is invalid.")
        if port != default_port:
            raise ControlledFetchError(
                "non_standard_port",
                "Only standard HTTP and HTTPS ports are allowed.",
            )

        host_for_url = f"[{host}]" if ":" in host else host
        netloc = host_for_url
        path = parsed.path or "/"
        normalized_url = urlunsplit((scheme, netloc, path, parsed.query, ""))
        request_target = urlunsplit(("", "", path, parsed.query, ""))

        try:
            records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ControlledFetchError("dns_resolution_failed", "URL host could not be resolved.") from exc

        addresses: list[_ResolvedAddress] = []
        seen: set[tuple[int, tuple[object, ...]]] = set()
        for family, _socktype, protocol, _canonical_name, sockaddr in records:
            if not sockaddr:
                continue
            ip_text = str(sockaddr[0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(ip_text)
            except ValueError as exc:
                raise ControlledFetchError("invalid_resolution", "URL host resolved to an invalid address.") from exc
            if _is_non_public_address(address):
                raise ControlledFetchError("blocked_address", "URL host resolved to a non-public address.")
            normalized_sockaddr = tuple(sockaddr)
            identity = (family, normalized_sockaddr)
            if identity in seen:
                continue
            seen.add(identity)
            if len(addresses) >= self.max_resolved_addresses:
                raise ControlledFetchError(
                    "dns_too_many_addresses",
                    "URL host resolved to too many public addresses.",
                )
            addresses.append(
                _ResolvedAddress(
                    family=family,
                    protocol=protocol,
                    sockaddr=normalized_sockaddr,
                )
            )

        if not addresses:
            raise ControlledFetchError("dns_no_addresses", "URL host did not resolve to a connectable public address.")

        return _ResolvedTarget(
            url=normalized_url,
            scheme=scheme,
            host=host,
            port=port,
            request_target=request_target,
            addresses=tuple(addresses),
        )

    def _request_once(
        self,
        target: _ResolvedTarget,
        *,
        headers: Mapping[str, str] | None,
        deadline: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        sock = self._connect_verified(target, deadline=deadline)
        connection = http.client.HTTPConnection(
            target.host,
            target.port,
            timeout=self._remaining_timeout(deadline),
        )
        connection.sock = sock
        try:
            sock.settimeout(self._remaining_timeout(deadline))
            connection.request("GET", target.request_target, headers=self._request_headers(headers))
            response = connection.getresponse()
            response_headers = {
                str(name).lower(): str(value)
                for name, value in response.getheaders()
            }
            status = int(response.status)
            if status in _REDIRECT_STATUSES:
                return status, response_headers, b""
            if status < 200 or status >= 300:
                raise ControlledFetchError("http_status", f"URL request returned HTTP {status}.")
            return status, response_headers, self._read_bounded_body(
                response,
                response_headers,
                deadline=deadline,
                sock=sock,
            )
        except ControlledFetchError:
            raise
        except socket.timeout as exc:
            raise ControlledFetchError("timeout", "URL request timed out.") from exc
        except ssl.SSLError as exc:
            raise ControlledFetchError("tls_failed", "URL TLS validation failed.") from exc
        except (http.client.HTTPException, OSError, ValueError) as exc:
            raise ControlledFetchError("request_failed", "URL request failed.") from exc
        finally:
            connection.close()

    def _connect_verified(
        self,
        target: _ResolvedTarget,
        *,
        deadline: float | None = None,
    ) -> socket.socket:
        failures: list[Exception] = []
        for address in target.addresses:
            sock = socket.socket(address.family, socket.SOCK_STREAM, address.protocol)
            try:
                sock.settimeout(self._remaining_timeout(deadline))
                sock.connect(address.sockaddr)
                if target.scheme == "https":
                    context = ssl.create_default_context()
                    return context.wrap_socket(sock, server_hostname=target.host)
                return sock
            except (OSError, ssl.SSLError) as exc:
                failures.append(exc)
                sock.close()
        if failures and isinstance(failures[-1], socket.timeout):
            raise ControlledFetchError("timeout", "URL connection timed out.") from failures[-1]
        raise ControlledFetchError("connection_failed", "URL host could not be reached through a verified address.")

    def _read_bounded_body(
        self,
        response: http.client.HTTPResponse,
        headers: Mapping[str, str],
        *,
        deadline: float | None = None,
        sock: socket.socket | None = None,
    ) -> bytes:
        content_length = headers.get("content-length", "").strip()
        if content_length:
            try:
                if int(content_length) > self.max_response_bytes:
                    raise ControlledFetchError("response_too_large", "URL response exceeded Trainer's size limit.")
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        while True:
            if sock is not None:
                sock.settimeout(self._remaining_timeout(deadline))
            remaining = self.max_response_bytes - total
            chunk = response.read(min(64 * 1024, remaining + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_response_bytes:
                raise ControlledFetchError("response_too_large", "URL response exceeded Trainer's size limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _remaining_timeout(self, deadline: float | None) -> float:
        if deadline is None:
            return self.timeout_seconds
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControlledFetchError("timeout", "URL request timed out.")
        return remaining

    @staticmethod
    def _request_headers(extra_headers: Mapping[str, str] | None) -> dict[str, str]:
        headers = {
            "User-Agent": "Trainer/1.0 controlled-source-fetch",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        }
        forbidden = {"host", "connection", "content-length", "transfer-encoding"}
        for name, value in (extra_headers or {}).items():
            normalized_name = str(name).strip()
            if not normalized_name or normalized_name.lower() in forbidden:
                continue
            headers[normalized_name] = str(value)
        return headers


def fetch_url(
    url: str,
    *,
    network_enabled: bool,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    headers: Mapping[str, str] | None = None,
) -> ControlledFetchResponse:
    """Fetch a source only when the caller explicitly has network authority."""

    return ControlledHttpFetcher(
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        max_redirects=max_redirects,
    ).fetch(url, network_enabled=network_enabled, headers=headers)


def _is_non_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    if mapped is not None:
        return _is_non_public_address(mapped)
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or not address.is_global
    )
