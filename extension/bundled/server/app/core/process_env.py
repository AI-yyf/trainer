"""Environment for processes the sidecar starts on the learner's behalf.

Learner code, project test suites and MCP servers run with the learner's own
privileges — that is the product. What they must never inherit is a way to
speak to *this* sidecar as if they were the workbench host: the per-instance
token is the credential this process injects into its own environment, and a
project's test suite that reads it could drive every trusted route.

Other ambient host variables (for example a shell-exported provider key) are
the learner's own environment and are deliberately left in place: these
children already run as the same user, and scrubbing every secret-shaped name
would also break user-configured MCP servers that receive credentials through
their own environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

SIDECAR_SECRET_ENV_VARS: tuple[str, ...] = ("TRAINER_SIDECAR_TOKEN",)


def child_process_environment(
    base: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """A copy of ``base`` (default: this process's environment) for a child.

    The sidecar's own secrets are removed. ``overrides`` are applied last, so
    an explicitly configured per-process setting still wins.
    """
    source = os.environ if base is None else base
    environment = {
        key: value for key, value in source.items() if key not in SIDECAR_SECRET_ENV_VARS
    }
    if overrides:
        environment.update({str(key): str(value) for key, value in overrides.items()})
    return environment
