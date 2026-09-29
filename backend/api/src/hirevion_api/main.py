"""The ASGI app uvicorn serves: `uvicorn hirevion_api.main:app` (or `uv run hv api`)."""

from importlib.metadata import version

from hirevion_api.app import create_app
from hirevion_core.logging import configure_logging
from hirevion_core.telemetry import setup_telemetry

configure_logging()
app = create_app(telemetry=setup_telemetry("hirevion-api", service_version=version("hirevion-api")))
