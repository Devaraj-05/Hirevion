import re

import hirevion_devcli


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", hirevion_devcli.__version__)
