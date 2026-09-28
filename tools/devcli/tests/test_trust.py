from pathlib import Path

from hirevion_devcli.stack import compose_command
from hirevion_devcli.trust import (
    CA_CONTAINER_PATH,
    LOCAL_CA_PATH,
    export_ca_command,
    trust_ca_command,
)


def test_export_ca_command_copies_caddy_root_certificate(tmp_path: Path) -> None:
    assert CA_CONTAINER_PATH == "/data/caddy/pki/authorities/local/root.crt"
    assert export_ca_command(tmp_path) == compose_command(
        tmp_path, ["edge"], "cp", f"caddy:{CA_CONTAINER_PATH}", str(tmp_path / LOCAL_CA_PATH)
    )


def test_trust_ca_command_uses_current_user_root_store() -> None:
    assert trust_ca_command(Path("caddy-root.crt")) == [
        "certutil",
        "-user",
        "-addstore",
        "Root",
        "caddy-root.crt",
    ]
