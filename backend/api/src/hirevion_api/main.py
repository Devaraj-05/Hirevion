"""The ASGI app uvicorn serves: `uvicorn hirevion_api.main:app` (or `uv run hv api`)."""

from hirevion_api.app import create_app

app = create_app()
