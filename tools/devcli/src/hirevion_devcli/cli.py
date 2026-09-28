"""Hirevion developer CLI. Run `uv run hv --help`."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import doctor as doctor_checks
from .checks import CheckResult
from .envfile import generate_local_secrets, init_env, parse_env, sync_env
from .hosts import HOSTS_PATH, ensure_hosts
from .smoke import run_smoke
from .stack import ALL_PROFILES, compose_command, select_profiles
from .trust import LOCAL_CA_PATH, export_ca_command, trust_ca_command

app = typer.Typer(help="Hirevion developer CLI.", no_args_is_help=True)
console = Console()

_STATUS_STYLE = {
    "ok": "[green]ok[/green]",
    "warn": "[yellow]warn[/yellow]",
    "fail": "[red]FAIL[/red]",
}


def repo_root() -> Path:
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "MASTER_IMPLEMENTATION_PLAN.md").exists():
            return candidate
    raise typer.BadParameter("Run this command inside the Hirevion repository.")


def _run_stream(command: list[str]) -> int:
    """Run a fixed command, streaming its output to the terminal (never a shell)."""
    return subprocess.run(command, check=False).returncode  # noqa: S603


def _require_env(root: Path) -> dict[str, str]:
    env_path = root / ".env"
    if not env_path.exists():
        console.print(".env is missing; run `uv run hv init-env` first.")
        raise typer.Exit(code=1)
    return parse_env(env_path.read_text(encoding="utf-8"))


def _print_results(title: str, results: Sequence[CheckResult]) -> None:
    table = Table(title=title)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for result in results:
        table.add_row(result.name, _STATUS_STYLE[result.status], result.detail)
    console.print(table)


def _elevated_copy(source: Path, destination: Path) -> int:
    """Copy source over destination from an elevated PowerShell (one UAC prompt)."""
    script = source.with_suffix(".ps1")
    script.write_text(
        f"Copy-Item -LiteralPath '{source}' -Destination '{destination}' -Force\r\n"
        "ipconfig /flushdns | Out-Null\r\n",
        encoding="utf-8",
    )
    arguments = f"'-NoProfile','-ExecutionPolicy','Bypass','-File','{script}'"
    return _run_stream(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Start-Process powershell -Verb RunAs -Wait -ArgumentList {arguments}",
        ]
    )


@app.command("init-env")
def init_env_command() -> None:
    """Create .env from .env.example with fresh local secrets (never overwrites)."""
    root = repo_root()
    if init_env(root / ".env.example", root / ".env"):
        console.print(
            "Created .env. Add GEMINI_API_KEY and DEEPGRAM_API_KEY to it, "
            "then run `uv run hv doctor`."
        )
    else:
        console.print(".env already exists; left unchanged.")


@app.command("env-sync")
def env_sync_command() -> None:
    """Add settings that are new in .env.example to .env (existing values are kept)."""
    root = repo_root()
    env_path = root / ".env"
    if not env_path.exists():
        console.print(".env is missing; run `uv run hv init-env` first.")
        raise typer.Exit(code=1)
    new_text, added = sync_env(
        (root / ".env.example").read_text(encoding="utf-8"),
        env_path.read_text(encoding="utf-8"),
        generate_local_secrets(),
    )
    if added:
        env_path.write_text(new_text, encoding="utf-8")
        console.print("Added to .env: " + ", ".join(added))
    else:
        console.print(".env is already up to date.")


@app.command()
def doctor() -> None:
    """Check tools, Docker, hostnames, .env and the AI vendor keys."""
    results, models = doctor_checks.gather(repo_root())
    _print_results("Hirevion doctor", results)
    for provider, provider_models in models.items():
        useful = doctor_checks.summarize_models(provider_models)
        if useful:
            console.print(f"{provider} models usable by Hirevion: " + ", ".join(useful))
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@app.command()
def up(
    obs: Annotated[bool, typer.Option("--obs", help="Also start Grafana and GlitchTip.")] = False,
) -> None:
    """Start the local stack and wait until every service is healthy."""
    root = repo_root()
    _require_env(root)
    command = compose_command(
        root,
        select_profiles(obs),
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "600",
        "--remove-orphans",
    )
    raise typer.Exit(code=_run_stream(command))


@app.command()
def down() -> None:
    """Stop the local stack (data is kept)."""
    root = repo_root()
    _require_env(root)
    raise typer.Exit(code=_run_stream(compose_command(root, ALL_PROFILES, "down")))


@app.command()
def reset(
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation.")] = False,
) -> None:
    """Stop the local stack and delete all local data (databases, storage, mail)."""
    root = repo_root()
    _require_env(root)
    if not yes and not typer.confirm("Delete all local Hirevion data?"):
        raise typer.Exit(code=1)
    raise typer.Exit(code=_run_stream(compose_command(root, ALL_PROFILES, "down", "--volumes")))


@app.command()
def ps() -> None:
    """Show the local stack's containers and their health."""
    root = repo_root()
    _require_env(root)
    raise typer.Exit(code=_run_stream(compose_command(root, ALL_PROFILES, "ps")))


@app.command()
def logs(
    service: Annotated[str | None, typer.Argument(help="Only this service.")] = None,
) -> None:
    """Follow the local stack's logs."""
    root = repo_root()
    _require_env(root)
    args = ["logs", "--follow", "--tail", "200", *([service] if service else [])]
    raise typer.Exit(code=_run_stream(compose_command(root, ALL_PROFILES, *args)))


@app.command()
def hosts() -> None:
    """Point *.hirevion.localhost at this PC in the Windows hosts file (asks for admin)."""
    missing = ensure_hosts(HOSTS_PATH, Path(tempfile.gettempdir()), _elevated_copy)
    if missing:
        console.print("These names still don't resolve to this PC: " + ", ".join(missing))
        raise typer.Exit(code=1)
    console.print("All *.hirevion.localhost names resolve to this PC.")


@app.command("trust-ca")
def trust_ca() -> None:
    """Trust Caddy's local certificate authority for your Windows user (Windows asks)."""
    root = repo_root()
    _require_env(root)
    (root / LOCAL_CA_PATH).parent.mkdir(parents=True, exist_ok=True)
    if _run_stream(export_ca_command(root)) != 0:
        console.print("Could not copy the certificate out of Caddy; is `uv run hv up` running?")
        raise typer.Exit(code=1)
    raise typer.Exit(code=_run_stream(trust_ca_command(root / LOCAL_CA_PATH)))


@app.command()
def smoke(
    obs: Annotated[bool, typer.Option("--obs", help="Also check Grafana and GlitchTip.")] = False,
) -> None:
    """Prove each local service works with a real round-trip."""
    root = repo_root()
    values = _require_env(root)
    results = run_smoke(root, values, obs)
    _print_results("Hirevion smoke checks", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
