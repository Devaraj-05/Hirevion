"""`hv interview-sim` (SP-09): one simulated candidate through a real interview on the running
API, in text mode. It seeds a synthetic job, candidate and library in the development
organisation (`hv seed-identity` first), signs in like the desktop app and answers as the
chosen persona; the transcript is then on the interview's page."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from uuid import UUID

import httpx

from hirevion_core.identity.settings import load_identity_settings
from hirevion_core.storage.service import load_optional_storage
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.personas import persona
from hirevion_interview_simulator.run import SimulationReport, simulate
from hirevion_interview_simulator.seed import NotSeeded, seed_development_interview
from hirevion_interview_simulator.telemetry import TelemetryReport, send_telemetry

__all__ = ["NotSeeded", "SimulationRun", "run_simulation"]


@dataclass(frozen=True)
class SimulationRun:
    report: SimulationReport
    interview_id: UUID
    interview_url: str
    telemetry: TelemetryReport | None = None


async def run_simulation(name: str, api_url: str, *, telemetry: bool = True) -> SimulationRun:
    """One simulated interview. With `telemetry` (the default) the desktop's proctoring events and
    recording segments are sent too, so the run has data for every part of the reports."""
    candidate = persona(name)
    seed = await seed_development_interview(text_answers=True, password=secrets.token_urlsafe(18))
    candidate.knowledge = dict(seed.knowledge)
    sent: list[TelemetryReport] = []
    async with httpx.AsyncClient(timeout=30) as http:
        desktop = DesktopClient(http, base_url=api_url)
        await desktop.login(seed.email, seed.password)

        async def after_start(client: DesktopClient, interview_id: str) -> None:
            storage = load_optional_storage()
            urls = (
                (storage.settings.public_endpoint, storage.settings.internal_endpoint)
                if storage is not None
                else None
            )
            sent.append(
                await send_telemetry(client, interview_id, uploader=http, storage_urls=urls)
            )
            if storage is not None:
                await storage.aclose()

        report = await simulate(
            desktop,
            str(seed.interview_id),
            candidate,
            after_start=after_start if telemetry else None,
        )
    url = f"{load_identity_settings().web_origin.rstrip('/')}/interviews/{seed.interview_id}"
    return SimulationRun(report, seed.interview_id, url, sent[0] if sent else None)
