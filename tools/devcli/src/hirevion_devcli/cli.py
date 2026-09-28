"""Hirevion developer CLI. Run `uv run hv --help`."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import doctor as doctor_checks
from .envfile import generate_local_secrets, init_env, sync_env

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


@app.command("init-env")
def init_env_command() -> None:
    """Create .env from .env.example with fresh local secrets (never overwrites)."""
    root = repo_root()
    if init_env(root / ".env.example", root / ".env"):
        console.print(
            "Created .env. Add OPENAI_API_KEY and DEEPGRAM_API_KEY to it, "
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
    """Check tools, Docker, .env and the AI vendor keys."""
    results, models = doctor_checks.gather(repo_root())
    table = Table(title="Hirevion doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for result in results:
        table.add_row(result.name, _STATUS_STYLE[result.status], result.detail)
    console.print(table)
    for provider, provider_models in models.items():
        useful = doctor_checks.summarize_models(provider_models)
        if useful:
            console.print(f"{provider} models usable by Hirevion: " + ", ".join(useful))
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
