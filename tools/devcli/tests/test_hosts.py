import socket
from collections.abc import Sequence
from typing import Any

from hirevion_devcli.hosts import BEGIN, END, apply_block, hostnames, render_block, unresolved


def test_hostnames_cover_every_local_site() -> None:
    names = hostnames()
    assert "app.hirevion.localhost" in names
    assert "api.hirevion.localhost" in names
    assert "livekit.hirevion.localhost" in names
    assert len(names) == len(set(names))


def test_render_block_has_one_line_per_name() -> None:
    block = render_block(["a.hirevion.localhost", "b.hirevion.localhost"])
    assert block.splitlines() == [
        BEGIN,
        "127.0.0.1 a.hirevion.localhost",
        "127.0.0.1 b.hirevion.localhost",
        END,
    ]


def test_apply_block_appends_and_keeps_existing_lines() -> None:
    hosts = "# comment\r\n127.0.0.1 localhost\r\n"
    updated = apply_block(hosts, render_block(["a.hirevion.localhost"]))
    assert updated.startswith("# comment\r\n127.0.0.1 localhost\r\n")
    assert "127.0.0.1 a.hirevion.localhost\r\n" in updated
    assert updated.endswith("\r\n")


def test_apply_block_replaces_previous_block_and_is_idempotent() -> None:
    first = apply_block("127.0.0.1 localhost\r\n", render_block(["old.hirevion.localhost"]))
    second = apply_block(first, render_block(["new.hirevion.localhost"]))
    assert "old.hirevion.localhost" not in second
    assert second.count(BEGIN) == 1
    assert apply_block(second, render_block(["new.hirevion.localhost"])) == second


def test_unresolved_reports_names_that_do_not_point_here() -> None:
    def fake_resolve(name: str, port: int) -> Sequence[tuple[Any, ...]]:
        if name == "good.hirevion.localhost":
            return [(socket.AF_INET, 1, 6, "", ("127.0.0.1", port))]
        if name == "remote.hirevion.localhost":
            return [(socket.AF_INET, 1, 6, "", ("10.0.0.5", port))]
        raise socket.gaierror("not found")

    names = ["good.hirevion.localhost", "remote.hirevion.localhost", "missing.hirevion.localhost"]
    assert unresolved(names, resolve=fake_resolve) == [
        "remote.hirevion.localhost",
        "missing.hirevion.localhost",
    ]
