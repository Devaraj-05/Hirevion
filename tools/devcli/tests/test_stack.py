from pathlib import Path

from hirevion_devcli.stack import compose_command, select_profiles


def test_select_profiles() -> None:
    assert select_profiles(include_obs=False) == ["core", "edge", "media"]
    assert select_profiles(include_obs=True) == ["core", "edge", "media", "obs"]


def test_compose_command_uses_project_env_file_and_profiles(tmp_path: Path) -> None:
    command = compose_command(tmp_path, ["core", "edge"], "up", "--detach")
    assert command == [
        "docker",
        "compose",
        "--project-name",
        "hirevion",
        "--env-file",
        str(tmp_path / ".env"),
        "--file",
        str(tmp_path / "infrastructure" / "local" / "compose.yaml"),
        "--profile",
        "core",
        "--profile",
        "edge",
        "up",
        "--detach",
    ]
