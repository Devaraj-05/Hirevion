from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jwt
import pytest
from typer.testing import CliRunner

from hirevion_devcli import cli

runner = CliRunner()
SECRET = "s" * 48


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "MASTER_IMPLEMENTATION_PLAN.md").write_text("# plan\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"LIVEKIT_API_KEY=hirevion-local\nLIVEKIT_API_SECRET={SECRET}\nLIVEKIT_NODE_IP=192.168.1.9\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return Path.cwd().resolve()


def claims(token: str) -> dict[str, Any]:
    decoded: dict[str, Any] = jwt.decode(
        token, SECRET, algorithms=["HS256"], options={"verify_nbf": False}
    )
    return decoded


def test_lk_token_prints_a_participant_token(repo: Path) -> None:
    result = runner.invoke(cli.app, ["lk-token", "--room", "spike", "--identity", "desktop"])
    assert result.exit_code == 0
    token = result.output.strip().splitlines()[-1]
    decoded = claims(token)
    assert decoded["sub"] == "desktop"
    assert decoded["video"]["room"] == "spike"
    assert decoded["video"]["canSubscribe"] is True


def test_lk_token_camera_only_limits_publishing(repo: Path) -> None:
    result = runner.invoke(
        cli.app, ["lk-token", "--room", "spike", "--identity", "phone", "--camera-only"]
    )
    video = claims(result.output.strip().splitlines()[-1])["video"]
    assert video["canPublishSources"] == ["camera"]
    assert video["canSubscribe"] is False


def test_lk_token_copy_puts_the_token_on_the_clipboard(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(cli, "_copy_to_clipboard", copied.append)
    result = runner.invoke(
        cli.app, ["lk-token", "--room", "spike", "--identity", "desktop", "--copy"]
    )
    assert result.exit_code == 0
    assert claims(copied[0])["sub"] == "desktop"
    assert copied[0] not in result.output


class FakeTunnel:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.terminated = False

    def lines(self) -> Iterator[str]:
        yield from self._lines

    def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        self.terminated = True


def test_eye_tunnel_refuses_a_loopback_node_ip(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / ".env").write_text(
        f"LIVEKIT_API_KEY=k\nLIVEKIT_API_SECRET={SECRET}\nLIVEKIT_NODE_IP=127.0.0.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "route_probe", lambda: "192.168.1.9")
    result = runner.invoke(cli.app, ["eye-tunnel"])
    assert result.exit_code == 1
    assert "192.168.1.9" in result.output


def test_eye_tunnel_prints_the_phone_link(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tunnel = FakeTunnel(
        [
            "INF Requesting new quick Tunnel on trycloudflare.com...",
            "INF |  https://brave-cat-lemon.trycloudflare.com   |",
        ]
    )
    started: list[list[str]] = []

    def fake_start(command: list[str]) -> FakeTunnel:
        started.append(command)
        return tunnel

    monkeypatch.setattr(cli, "find_cloudflared", lambda: "cloudflared")
    monkeypatch.setattr(cli, "_start_tunnel", fake_start)
    monkeypatch.setattr(cli, "_print_qr", lambda link: None)
    result = runner.invoke(cli.app, ["eye-tunnel", "--room", "spike"])
    assert result.exit_code == 0, result.output
    assert started == [["cloudflared", "tunnel", "--no-autoupdate", "--url", cli.TUNNEL_TARGET]]
    link = next(line for line in result.output.split() if line.startswith("https://brave-cat"))
    token = link.split("#t=", 1)[1]
    assert claims(token)["video"]["canPublishSources"] == ["camera"]
    assert tunnel.terminated


def test_eye_tunnel_page_only_prints_the_address_for_real_pairing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tunnel = FakeTunnel(["INF |  https://quiet-owl-river.trycloudflare.com   |"])
    monkeypatch.setattr(cli, "find_cloudflared", lambda: "cloudflared")
    monkeypatch.setattr(cli, "_start_tunnel", lambda command: tunnel)
    monkeypatch.setattr(cli, "_print_qr", lambda link: pytest.fail("no QR without a token"))
    result = runner.invoke(cli.app, ["eye-tunnel", "--page-only"])
    assert result.exit_code == 0, result.output
    assert "HV_THIRD_EYE_URL=https://quiet-owl-river.trycloudflare.com" in result.output
    assert "#t=" not in result.output
    assert tunnel.terminated


def test_eye_tunnel_explains_a_missing_cloudflared(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "find_cloudflared", lambda: None)
    result = runner.invoke(cli.app, ["eye-tunnel"])
    assert result.exit_code == 1
    assert "winget install --id Cloudflare.cloudflared" in result.output
