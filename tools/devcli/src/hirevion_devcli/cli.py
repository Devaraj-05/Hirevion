"""Hirevion developer CLI. Run `uv run hv --help`."""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Annotated

import segno
import typer
from rich.console import Console
from rich.table import Table

from hirevion_core.db.migrate import migrate as migrate_database
from hirevion_core.identity.bootstrap import AccountExists, ProductionRefused, seed_emails
from hirevion_core.settings import load_core_settings
from hirevion_core.storage.service import ensure_storage, load_storage_settings

from . import doctor as doctor_checks
from .checks import CheckResult
from .envfile import generate_local_secrets, init_env, parse_env, sync_env
from .hosts import HOSTS_PATH, ensure_hosts
from .identity import invite_super_admin, reset_rate_limits, seed, work
from .livekit import (
    Grants,
    build_token,
    detect_lan_ip,
    is_lan_ip,
    parse_tunnel_url,
    phone_link,
    route_probe,
)
from .smoke import run_smoke
from .stack import ALL_PROFILES, compose_command, select_profiles
from .trust import LOCAL_CA_PATH, export_ca_command, trust_ca_command

app = typer.Typer(help="Hirevion developer CLI.", no_args_is_help=True)

# Caddy's plain-HTTP site for tunnels (/rtc -> LiveKit, everything else -> third-eye dev server).
TUNNEL_TARGET = "http://127.0.0.1:8088"
CLOUDFLARED_INSTALL = "winget install --id Cloudflare.cloudflared"
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
def api(
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Restart when backend code changes.")] = True,
) -> None:
    """Run the API; Caddy serves it at https://api.hirevion.localhost (needs `hv up`)."""
    root = repo_root()
    _require_env(root)
    command = [sys.executable, "-m", "uvicorn", "hirevion_api.main:app", "--host", "127.0.0.1"]
    command += ["--port", str(port), "--no-access-log"]
    if reload:
        command += ["--reload", "--reload-dir", str(root / "backend")]
    raise typer.Exit(code=_run_stream(command))


OPENAPI_DOCUMENT = Path("packages/api-client/openapi.json")


@app.command()
def openapi(
    check: Annotated[bool, typer.Option("--check", help="Only compare; fail if stale.")] = False,
) -> None:
    """Write the API's OpenAPI document for the TypeScript client (or check it is current)."""
    command = [sys.executable, "-m", "hirevion_api.openapi", str(repo_root() / OPENAPI_DOCUMENT)]
    raise typer.Exit(code=_run_stream(command + (["--check"] if check else [])))


# Web apps that upload straight to storage with signed URLs (the desktop uploads from Rust).
STORAGE_ORIGINS = [
    "https://app.hirevion.localhost",
    "https://candidate.hirevion.localhost",
    "https://eye.hirevion.localhost",
]


@app.command("storage-init")
def storage_init() -> None:
    """Create the private blob container and allow browser uploads from the web apps."""
    try:
        asyncio.run(ensure_storage(load_storage_settings(), STORAGE_ORIGINS))
    except OSError as error:
        console.print(f"Could not reach blob storage ({error}); is `uv run hv up` running?")
        raise typer.Exit(code=1) from error
    console.print("Blob storage is ready.")


@app.command("migrate")
def migrate_command(
    database: Annotated[
        str | None, typer.Option(help="Database to migrate (default: POSTGRES_DB).")
    ] = None,
) -> None:
    """Create the database roles and apply every migration."""
    root = repo_root()
    _require_env(root)
    try:
        asyncio.run(migrate_database(load_core_settings(), database))
    except OSError as error:
        console.print(f"Could not reach PostgreSQL ({error}); is `uv run hv up` running?")
        raise typer.Exit(code=1) from error
    console.print(f"Migrated {database or 'the default database'}.")


@app.command("create-super-admin")
def create_super_admin_command(
    email: Annotated[str, typer.Option(help="The super admin's email address.")],
    name: Annotated[str, typer.Option(help="Their name, as the app shows it.")],
) -> None:
    """Invite a platform super admin and print their one-time set-password link."""
    _require_env(repo_root())
    try:
        link = asyncio.run(invite_super_admin(email, name))
    except AccountExists:
        console.print(f"An account already uses {email}.")
        raise typer.Exit(code=1) from None
    console.print(f"Invited {email}. Open this link within 72 hours to set a password:")
    # Plain, on its own line: Rich would colour and might wrap it, which breaks copying.
    typer.echo(link)


@app.command("seed-identity")
def seed_identity_command() -> None:
    """Create the development organisation with one user per role (password: HV_SEED_PASSWORD)."""
    values = _require_env(repo_root())
    environment = os.environ.get("HV_ENVIRONMENT") or values.get("HV_ENVIRONMENT", "development")
    if environment == "production":
        console.print("Refusing to seed development users with HV_ENVIRONMENT=production.")
        raise typer.Exit(code=1)
    password = os.environ.get("HV_SEED_PASSWORD") or values.get("HV_SEED_PASSWORD", "")
    if len(password) < 15:
        console.print("Set HV_SEED_PASSWORD (15+ characters) in .env, e.g. `uv run hv env-sync`.")
        raise typer.Exit(code=1)
    try:
        result = asyncio.run(seed(password, environment))
    except ProductionRefused:
        console.print("Refusing to seed development users in production.")
        raise typer.Exit(code=1) from None
    created = set(result.created)
    for email in seed_emails():
        console.print(f"{email}  {'created' if email in created else 'already there'}")
    console.print("They sign in with the HV_SEED_PASSWORD from .env.")


@app.command("reset-limits")
def reset_limits_command() -> None:
    """Clear every rate limit and sign-in lockout in the local Valkey (development only)."""
    values = _require_env(repo_root())
    environment = os.environ.get("HV_ENVIRONMENT") or values.get("HV_ENVIRONMENT", "development")
    if environment == "production":
        console.print("Refusing to clear rate limits with HV_ENVIRONMENT=production.")
        raise typer.Exit(code=1)
    removed = asyncio.run(reset_rate_limits())
    console.print(f"Cleared {removed} rate-limit and lockout entries.")


RESUMES_DIR = Path("tools/devcli/.cache/resumes")
RESUME_REPORT = Path("docs/evals/2026-10-resume-parse.md")


@app.command("synth-resumes")
def synth_resumes_command(
    out: Annotated[Path, typer.Option(help="Where to write the files.")] = RESUMES_DIR,
    count: Annotated[int, typer.Option(min=1, max=200)] = 200,
    seed: Annotated[int, typer.Option(help="Same seed, same resumes.")] = 7,
) -> None:
    """Write the synthetic resumes, with their true values, for `hv eval-resumes`."""
    from .synthetic_resumes import generate

    target = out if out.is_absolute() else repo_root() / out
    truths = generate(target, count=count, seed=seed)
    console.print(f"Wrote {len(truths)} resumes and bundle.zip to {target}.")


@app.command("trace")
def trace_command(
    check_only: Annotated[
        bool, typer.Option("--check", help="Exit 1 when the checklist has problems.")
    ] = False,
) -> None:
    """Check the PRD traceability checklist (master plan Appendix A) against the code."""
    from .trace import appendix_rows, check

    root = repo_root()
    problems = check(root)
    rows = appendix_rows((root / "MASTER_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8"))
    for problem in problems:
        console.print(f"[red]✗[/red] {problem}")
    console.print(f"{len(rows)} rows, {len(problems)} problem(s).")
    if problems and check_only:
        raise typer.Exit(code=1)


@app.command("interview-sim")
def interview_sim_command(
    persona_name: Annotated[
        str,
        typer.Option("--persona", help="strong, partial, weak, silent, adversarial or cheating."),
    ] = "strong",
    api: Annotated[str, typer.Option(help="The running API (`hv api`).")] = "http://127.0.0.1:8000",
    telemetry: Annotated[
        bool,
        typer.Option(
            "--telemetry/--no-telemetry",
            help="Also send the desktop's proctoring events and recording segments.",
        ),
    ] = True,
    password: Annotated[
        str | None,
        typer.Option(
            help="The simulated candidate's password, to sign in to the portal as them "
            "(a throwaway one is made otherwise).",
        ),
    ] = None,
) -> None:
    """Run one simulated candidate through a text-mode interview on the running API."""
    from .interview_sim import NotSeeded, run_simulation

    values = _require_env(repo_root())
    if (os.environ.get("HV_ENVIRONMENT") or values.get("HV_ENVIRONMENT")) == "production":
        console.print("Refusing to simulate interviews with HV_ENVIRONMENT=production.")
        raise typer.Exit(code=1)
    try:
        run = asyncio.run(run_simulation(persona_name, api, telemetry=telemetry, password=password))
    except NotSeeded:
        console.print("Run `uv run hv seed-identity` first: the simulator uses its recruiter.")
        raise typer.Exit(code=1) from None
    except ValueError as error:
        console.print(str(error))
        raise typer.Exit(code=1) from None
    table = Table("#", "Question", "Answer")
    for index, exchange in enumerate(run.report.exchanges, start=1):
        table.add_row(str(index), exchange.question[:70], exchange.answer[:50] or "(silence)")
    console.print(table)
    console.print(f"{run.report.persona}: {run.report.status}. Transcript: {run.interview_url}")
    if run.telemetry is not None:
        console.print(
            f"Sent {run.telemetry.events} proctoring events and "
            f"{run.telemetry.segments} recording segments."
        )
    # Unwrapped, for scripts (the end-to-end suite reads it).
    typer.echo(f"interview_id={run.interview_id}")
    typer.echo(f"candidate_email={run.candidate_email}")
    if not run.report.finished:
        raise typer.Exit(code=1)


@app.command("audit-tail")
def audit_tail_command(
    action: Annotated[
        str | None, typer.Option(help="Only this action, e.g. report.viewed.")
    ] = None,
    resource: Annotated[
        str | None, typer.Option(help="Only entries about this resource id.")
    ] = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON for scripts.")] = False,
) -> None:
    """Show the development organisation's newest audit-log entries (read-only)."""
    from .audit_tail import as_json, audit_tail

    _require_env(repo_root())
    rows = asyncio.run(audit_tail(action=action, resource=resource, limit=limit))
    if json_output:
        typer.echo(as_json(rows))
        return
    table = Table("#", "When", "Action", "Actor", "Resource")
    for row in rows:
        table.add_row(
            str(row.seq),
            row.occurred_at[:19],
            row.action,
            f"{row.actor_type}:{(row.actor_id or '')[:8]}",
            f"{row.resource_type}:{(row.resource_id or '')[:8]}",
        )
    console.print(table)


@app.command("eval-resumes")
def eval_resumes_command(
    directory: Annotated[
        Path, typer.Option("--dir", help="From `hv synth-resumes`.")
    ] = RESUMES_DIR,
    limit: Annotated[int | None, typer.Option(min=1, help="Only the first N resumes.")] = None,
    parallel: Annotated[int, typer.Option(min=1, max=8)] = 4,
    report: Annotated[Path, typer.Option(help="Where to write the results.")] = RESUME_REPORT,
) -> None:
    """Run the resume pipeline over the synthetic set with the configured AI, and score it."""
    from .resume_eval import TARGET_CONTACT, TARGET_OVERALL, evaluate

    _require_env(repo_root())
    source = directory if directory.is_absolute() else repo_root() / directory
    if not (source / "truth.jsonl").exists():
        console.print(f"No synthetic set in {source}; run `uv run hv synth-resumes` first.")
        raise typer.Exit(code=1)
    result, profile, model = asyncio.run(
        evaluate(source, limit=limit, parallel=parallel, log=console.print)
    )
    target = report if report.is_absolute() else repo_root() / report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.markdown(profile, model), encoding="utf-8", newline="\n")
    table = Table("Field", "Precision", "Recall", "F1")
    for name, score in [*result.fields.items(), ("overall", result.overall)]:
        table.add_row(name, f"{score.precision:.3f}", f"{score.recall:.3f}", f"{score.f1:.3f}")
    console.print(table)
    console.print(
        f"Targets: F1 >= {TARGET_OVERALL} overall, >= {TARGET_CONTACT} for name, email, phone: "
        f"{'met' if result.met() else 'NOT met'}. Report: {target}"
    )
    if not result.met():
        raise typer.Exit(code=1)


SCREENING_REPORT = Path("docs/evals/2026-10-screening.md")


@app.command("eval-screening")
def eval_screening_command(
    directory: Annotated[
        Path, typer.Option("--dir", help="From `hv synth-resumes`.")
    ] = RESUMES_DIR,
    limit: Annotated[int, typer.Option(min=10, max=200, help="Candidates per job.")] = 60,
    report: Annotated[Path, typer.Option(help="Where to write the results.")] = SCREENING_REPORT,
) -> None:
    """Rank the evaluation candidates for three made-up jobs and score the ranking (run
    `hv eval-resumes` first)."""
    from .screening_eval import TARGET_NDCG, evaluate

    _require_env(repo_root())
    source = directory if directory.is_absolute() else repo_root() / directory
    result, profile = asyncio.run(evaluate(source / "truth.jsonl", limit=limit, log=console.print))
    target = report if report.is_absolute() else repo_root() / report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.markdown(profile), encoding="utf-8")
    console.print(
        f"Mean NDCG@10 {result.ndcg:.3f} (target {TARGET_NDCG}): "
        f"{'met' if result.met() else 'NOT met'}. Report: {target}"
    )
    if not result.met():
        raise typer.Exit(code=1)


INTERVIEW_REPORT = Path("docs/evals/2026-10-interviews.md")


@app.command("eval-interviews")
def eval_interviews_command(
    live: Annotated[
        bool, typer.Option("--live", help="Use the configured AI vendor, not the mock.")
    ] = False,
    prompt_version: Annotated[
        str | None, typer.Option(help="Try this prompt version (a file in evaluation/prompts).")
    ] = None,
    prompt_file: Annotated[
        Path | None, typer.Option(help="Try the prompt in this file (its name is its version).")
    ] = None,
    rubric_version: Annotated[str | None, typer.Option(help="Try this rubric version.")] = None,
    no_baseline: Annotated[
        bool, typer.Option("--no-baseline", help="Check the thresholds only.")
    ] = False,
    update_baseline: Annotated[
        bool, typer.Option("--update-baseline", help="Record the metrics of a passing run.")
    ] = False,
    report: Annotated[Path | None, typer.Option(help="Write the results as Markdown.")] = None,
) -> None:
    """Run the interview evaluator over the labelled set and apply the gate. Fails (exit 1)
    when a prompt or rubric change regresses; the mock profile needs no keys."""
    from hirevion_core.evaluation.harness import report_markdown

    from .interview_eval import NotUsable, run_gate
    from .interview_eval import update_baseline as write_baseline

    try:
        outcome = asyncio.run(
            run_gate(
                live=live,
                prompt_version=prompt_version,
                prompt_file=prompt_file,
                rubric_version=rubric_version,
                use_baseline=not no_baseline,
            )
        )
    except NotUsable as error:
        console.print(str(error))
        raise typer.Exit(code=1) from None
    table = Table("Check", "Result", "Value", "Threshold or baseline")
    for check in outcome.result.checks:
        table.add_row(
            check["name"],
            "[green]pass[/green]" if check["ok"] else "[red]FAIL[/red]",
            str(check.get("value", "")),
            str(check.get("threshold", check.get("baseline", ""))),
        )
    console.print(table)
    for failure in outcome.result.failures:
        console.print(f"[red]x[/red] {failure}")
    if report is not None:
        target = report if report.is_absolute() else Path.cwd() / report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            report_markdown(outcome.run, outcome.result, outcome.profile),
            encoding="utf-8",
            newline="\n",
        )
        console.print(f"Report: {target}")
    verdict = "passed" if outcome.result.passed else "BLOCKED"
    console.print(
        f"Gate {verdict}: prompt {outcome.run.prompt_version}, "
        f"rubric {outcome.run.rubric_version}, AI profile {outcome.profile}."
    )
    if not outcome.result.passed:
        raise typer.Exit(code=1)
    if update_baseline:
        console.print(f"Baseline written: {write_baseline(outcome.run)}")


@app.command("eval-rerun")
def eval_rerun_command(
    interview_id: Annotated[str, typer.Argument(help="The interview's id.")],
    dimension: Annotated[float, typer.Option(min=0, help="Allowed move per dimension.")] = 1.0,
    overall: Annotated[
        float, typer.Option(min=0, help="Allowed move per question and overall.")
    ] = 0.5,
) -> None:
    """Repeat an interview's evaluation with the prompt, rubric and skill weights it recorded,
    and report the difference. Exits 1 when it is outside the tolerance."""
    from uuid import UUID

    from hirevion_core.access.errors import AccessError
    from hirevion_core.evaluation.compare import Tolerance

    from .interview_eval import NotUsable, rerun

    _require_env(repo_root())
    try:
        target = UUID(interview_id)
    except ValueError:
        console.print("Give the interview's id (a UUID).")
        raise typer.Exit(code=1) from None
    try:
        evaluation = asyncio.run(rerun(target, Tolerance(dimension, overall)))
    except (NotUsable, AccessError) as error:
        console.print(getattr(error, "title", str(error)))
        raise typer.Exit(code=1) from None
    diff = evaluation.diff or {}
    table = Table("Question", "Original", "Re-run", "Moved", "Largest dimension move")
    for item in diff.get("questions", []):
        table.add_row(
            item["question_id"][:8],
            f"{item['base']:.2f}",
            f"{item['rerun']:.2f}",
            f"{item['diff']:.2f}",
            f"{item['max_dimension_diff']:.2f}",
        )
    console.print(table)
    final = diff.get("overall", {})
    console.print(
        f"Overall {final.get('base')} -> {final.get('rerun')}. Prompt {evaluation.prompt_version}, "
        f"rubric {evaluation.rubric_version}, model {diff.get('models', {}).get('rerun')}."
    )
    if diff.get("inputs_changed"):
        console.print(f"The transcript changed for: {', '.join(diff['inputs_changed'])}")
    if diff.get("model_changed"):
        console.print("The model differs from the one the evaluation used.")
    within = bool(diff.get("within_tolerance"))
    console.print(
        f"Within tolerance ({dimension} per dimension, {overall} per question): "
        f"{'yes' if within else 'NO'}."
    )
    if not within:
        raise typer.Exit(code=1)


@app.command()
def worker() -> None:
    """Relay the outbox and send email until Ctrl+C (for an API with HV_API_RUN_WORKERS=false)."""
    _require_env(repo_root())
    console.print("Relaying the outbox and sending email; Ctrl+C stops.")
    try:
        asyncio.run(work())
    except KeyboardInterrupt:
        console.print("Stopped.")


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


def _copy_to_clipboard(text: str) -> None:
    subprocess.run(["clip.exe"], input=text, text=True, check=True)  # noqa: S607


def _print_qr(link: str) -> None:
    segno.make(link, error="l").terminal(compact=True)


def find_cloudflared() -> str | None:
    """cloudflared on PATH, or where winget installs it."""
    found = shutil.which("cloudflared")
    if found:
        return found
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        candidate = Path(base or "") / "cloudflared" / "cloudflared.exe"
        if base and candidate.exists():
            return str(candidate)
    return None


class _Tunnel:
    """A running cloudflared quick tunnel; cloudflared logs to stderr."""

    def __init__(self, command: list[str]) -> None:
        self._process = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def lines(self) -> Iterator[str]:
        if self._process.stderr is not None:
            yield from self._process.stderr

    def wait(self) -> int:
        return self._process.wait()

    def terminate(self) -> None:
        self._process.terminate()


def _start_tunnel(command: list[str]) -> _Tunnel:
    return _Tunnel(command)


def _livekit_keys(values: dict[str, str]) -> tuple[str, str]:
    key, secret = values.get("LIVEKIT_API_KEY", ""), values.get("LIVEKIT_API_SECRET", "")
    if not key or not secret:
        console.print("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env.")
        raise typer.Exit(code=1)
    return key, secret


@app.command("lk-token")
def lk_token(
    room: Annotated[str, typer.Option(help="Room to join.")],
    identity: Annotated[str, typer.Option(help="Participant identity.")],
    camera_only: Annotated[
        bool, typer.Option("--camera-only", help="Only allow publishing a camera (third eye).")
    ] = False,
    ttl: Annotated[int, typer.Option(help="Seconds the token stays valid.")] = 600,
    copy: Annotated[
        bool, typer.Option("--copy", help="Copy the token to the clipboard instead of printing.")
    ] = False,
) -> None:
    """Mint a short-lived LiveKit token for the local stack (development only)."""
    key, secret = _livekit_keys(_require_env(repo_root()))
    grants = Grants.camera_only(room) if camera_only else Grants.participant(room)
    token = build_token(
        key,
        secret,
        identity=identity,
        name=identity,
        grants=grants,
        ttl_seconds=ttl,
        now=int(time.time()),
    )
    if copy:
        _copy_to_clipboard(token)
        console.print(f"Token for {identity} in {room} copied to the clipboard (valid {ttl} s).")
    else:
        typer.echo(token)


@app.command("eye-tunnel")
def eye_tunnel(
    room: Annotated[str, typer.Option(help="Room the phone joins.")] = "spike",
    ttl: Annotated[int, typer.Option(help="Seconds the phone's token stays valid.")] = 900,
    page_only: Annotated[
        bool,
        typer.Option(
            "--page-only",
            help="Mint no token: open the tunnel for real pairing (the desktop's QR code).",
        ),
    ] = False,
) -> None:
    """Open the third-eye page to a phone through a Cloudflare quick tunnel (development only)."""
    values = _require_env(repo_root())
    key, secret = _livekit_keys(values)
    node_ip = values.get("LIVEKIT_NODE_IP", "")
    if not is_lan_ip(node_ip):
        detected = detect_lan_ip(route_probe)
        hint = (
            f"this PC's LAN address looks like {detected}"
            if detected
            else "find this PC's LAN address with `ipconfig`"
        )
        console.print(
            f"LIVEKIT_NODE_IP is {node_ip or 'not set'}, so a phone can't reach LiveKit's media "
            f"ports. Set it in .env ({hint}), then run `uv run hv up`."
        )
        raise typer.Exit(code=1)
    cloudflared = find_cloudflared()
    if cloudflared is None:
        console.print(
            f"cloudflared is not installed. Run `{CLOUDFLARED_INSTALL}`, then open a new terminal."
        )
        raise typer.Exit(code=1)

    tunnel = _start_tunnel([cloudflared, "tunnel", "--no-autoupdate", "--url", TUNNEL_TARGET])
    try:
        url = next(filter(None, map(parse_tunnel_url, tunnel.lines())), None)
        if url is None:
            console.print("cloudflared stopped before reporting a tunnel address.")
            raise typer.Exit(code=1)
        if page_only:
            # SP-13: the API issues the pairing; its QR code must point at this tunnel.
            console.print("Set this in .env and restart the API, then pair from the desktop:")
            typer.echo(f"HV_THIRD_EYE_URL={url}")
            console.print("Keep this running while you test; press Ctrl+C to close the tunnel.")
            tunnel.wait()
            return
        token = build_token(
            key,
            secret,
            identity=f"third-eye-{secrets.token_hex(3)}",
            name="Third eye",
            grants=Grants.camera_only(room),
            ttl_seconds=ttl,
            now=int(time.time()),
        )
        link = phone_link(url, token)
        console.print(f"Open this on a phone on the same Wi-Fi (valid {ttl // 60} minutes):")
        typer.echo(link)
        _print_qr(link)
        console.print("Keep this running while you test; press Ctrl+C to close the tunnel.")
        tunnel.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.terminate()
