"""Authority-qualified remote project identities; never local filesystem paths."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit


def canonical_remote_project_uri(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    authority = unquote(parsed.netloc)
    path = unquote(parsed.path)
    if (
        parsed.scheme != "vscode-remote"
        or not re.fullmatch(r"[a-z][a-z0-9-]*\+[^/?#@:\s]+", authority)
        or not path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(segment in {".", ".."} for segment in path.split("/"))
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("An authority-qualified remote workspace URI is required.")
    return urlunsplit(("vscode-remote", authority, quote(posixpath.normpath(path), safe="/:@-._~!$&'()*+,;="), "", ""))


@dataclass(frozen=True)
class RemoteProjectIdentity:
    uri: str
    observed_uri: str
    remote_name: str


def validate_remote_project_identity(value: object) -> RemoteProjectIdentity:
    if not isinstance(value, dict) or value.get("protocol_version") != 2 or value.get("directory") is not True:
        raise ValueError("Remote adoption requires a host-observed Companion directory.")
    uri = canonical_remote_project_uri(str(value.get("canonical_uri") or ""))
    observed = canonical_remote_project_uri(str(value.get("workspace_uri") or ""))
    remote_name = str(value.get("remote_name") or "").strip()
    if not remote_name or urlsplit(uri).netloc != urlsplit(observed).netloc:
        raise ValueError("Remote project authority changed during adoption.")
    return RemoteProjectIdentity(uri=uri, observed_uri=observed, remote_name=remote_name)


def validate_remote_verification_artifact(value: object, project_uri: str) -> dict[str, str]:
    """Validate the host observation against the durable remote project lane."""
    if not isinstance(value, dict) or value.get("execution_location") != "remote":
        raise ValueError("Remote verification requires a host-observed remote artifact.")
    project = canonical_remote_project_uri(project_uri)
    workspace = canonical_remote_project_uri(str(value.get("workspace_uri") or ""))
    artifact = canonical_remote_project_uri(str(value.get("artifact_uri") or ""))
    root, target = urlsplit(project), urlsplit(artifact)
    if workspace != project or target.netloc != root.netloc or not unquote(target.path).startswith(unquote(root.path).rstrip("/") + "/"):
        raise ValueError("The verification artifact does not belong to the provisioned remote project.")
    sha256 = str(value.get("sha256") or "")
    session_id = str(value.get("companion_session_id") or "").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", sha256) or not session_id or len(session_id) > 256:
        raise ValueError("A stable SHA-256 and Companion session are required for remote evidence.")
    return {"workspace_uri": workspace, "artifact_uri": artifact, "sha256": sha256,
            "companion_session_id": session_id, "execution_location": "remote"}
