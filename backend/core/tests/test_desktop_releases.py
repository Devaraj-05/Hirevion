"""Release versions and staged rollouts (SP-07c Task 5); no database needed."""

import pytest

from hirevion_core.access.errors import Invalid
from hirevion_core.desktop.releases import Version, in_rollout, parse_version


def test_versions_order_semantically_with_pre_releases_first() -> None:
    ordered = ["1.4.0", "1.5.0-beta.1", "1.5.0-beta.2", "1.5.0-rc.1", "1.5.0", "1.10.0", "2.0.0"]
    parsed = [Version.parse(text) for text in ordered]
    assert parsed == sorted(parsed)
    assert Version.parse("1.5.0-beta.10") > Version.parse("1.5.0-beta.2")


@pytest.mark.parametrize("text", ["1.4", "v1.4.0", "1.4.0.1", "", "one"])
def test_other_strings_are_refused(text: str) -> None:
    with pytest.raises(Invalid):
        parse_version(text)


def test_a_rollout_is_stable_per_device_and_only_grows() -> None:
    devices = [f"device-{n}" for n in range(1000)]
    at_10 = {d for d in devices if in_rollout(d, "1.5.0", 10)}
    at_50 = {d for d in devices if in_rollout(d, "1.5.0", 50)}
    assert 50 < len(at_10) < 150 and 400 < len(at_50) < 600
    assert at_10 <= at_50
    assert at_10 == {d for d in devices if in_rollout(d, "1.5.0", 10)}


def test_without_a_device_only_full_rollouts_count() -> None:
    assert in_rollout(None, "1.5.0", 100)
    assert not in_rollout(None, "1.5.0", 99)
    assert not in_rollout("device", "1.5.0", 0)
