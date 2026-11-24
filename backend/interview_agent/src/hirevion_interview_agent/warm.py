"""Work done once per job runner, before an interview arrives, so none of it runs on the
agent's event loop while the interviewer speaks.

On the owner's run of 2026-11-21 the first runner was made only when the interview's job came
(dev mode keeps none waiting), its setup timed out after LiveKit's 10 s, and the next runner then
loaded the database driver (0.9 s) and configured the ORM (0.4 s) on the event loop during the
greeting: the voice broke up. On Windows, jobs run as threads of the agent's own process.
"""

from __future__ import annotations

import importlib
import math
import sys

from livekit.agents import JobProcess
from livekit.agents.utils.hw import get_cpu_monitor
from livekit.agents.worker import ServerEnvOption
from livekit.plugins import silero

from .priority import favour_live_audio

# One runner waits ready in dev mode too (LiveKit keeps none); production keeps LiveKit's own
# default, one per CPU.
IDLE_RUNNERS = ServerEnvOption(dev_default=1, prod_default=math.ceil(get_cpu_monitor().cpu_count()))
# A busy laptop needs more than LiveKit's 10 s to load the voice activity model.
INITIALIZE_TIMEOUT_SECONDS = 60.0


def warm_up() -> None:
    """Loads what the first database query would otherwise load on the event loop."""
    from sqlalchemy.orm import configure_mappers

    import hirevion_core.models  # noqa: F401  # every mapped class, for configure_mappers

    configure_mappers()
    # SQLAlchemy imports its driver only when the first engine connects.
    importlib.import_module("asyncpg")
    # The turn detector, when in use, reads its language list through huggingface_hub's download
    # (and filelock) as the session starts: 0.3 s on the event loop as the greeting began.
    if "livekit.plugins.turn_detector" in sys.modules:
        importlib.import_module("huggingface_hub.file_download")


def prewarm(process: JobProcess) -> None:
    # A job process in production: live audio runs before background work (perf, 2026-11-24).
    favour_live_audio()
    process.userdata["vad"] = silero.VAD.load()
    warm_up()
