"""uvicorn, which serves the API, accepts websocket upgrades: the live transcript and proctoring
feeds (`/ws/interviews/{id}`, `/ws/proctoring/{id}`) need a websocket implementation installed.
The other tests drive the app in-process, so they can't notice when it's missing."""

import asyncio
import socket

import uvicorn
from fastapi import FastAPI, WebSocket


async def test_uvicorn_serves_websocket_routes() -> None:
    import websockets  # the implementation uvicorn's `ws="auto"` picks

    app = FastAPI()

    @app.websocket("/ws/echo")
    async def echo(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/echo") as client:
            assert await client.recv() == "hello"
    finally:
        server.should_exit = True
        await serving
