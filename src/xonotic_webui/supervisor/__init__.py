"""Supervision of the Xonotic dedicated server child process.

* :mod:`xonotic_webui.supervisor.state` — the four-state model and guarded transitions.
* :mod:`xonotic_webui.supervisor.process` — spawning the server and owning its stdio.
* :mod:`xonotic_webui.supervisor.supervisor` — the orchestrator the rest of the panel uses.
"""

from xonotic_webui.supervisor.state import RunState, TransitionError
from xonotic_webui.supervisor.supervisor import (
    AlreadyRunningError,
    CrashInfo,
    NoInstallationError,
    NotRunningError,
    ReadinessTimeoutError,
    StartFailedError,
    StartFailure,
    Supervisor,
    SupervisorError,
    TransitionInProgressError,
)

__all__ = [
    "AlreadyRunningError",
    "CrashInfo",
    "NoInstallationError",
    "NotRunningError",
    "ReadinessTimeoutError",
    "RunState",
    "StartFailedError",
    "StartFailure",
    "Supervisor",
    "SupervisorError",
    "TransitionError",
    "TransitionInProgressError",
]
