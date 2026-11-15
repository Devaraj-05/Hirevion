"""The phone tunnel's Caddy site (local development, `hv eye-tunnel`).

The phone calls the API through a Cloudflare quick tunnel, so its requests arrive with a
`*.trycloudflare.com` Host, which the API's host check refuses (`host-not-allowed`, the
product owner's first real-phone try, 2026-11-15). The tunnel site must hand the API a Host it
answers to.
"""

import re
from pathlib import Path

from hirevion_api.settings import ApiSettings

CADDYFILE = Path(__file__).resolve().parents[3] / "infrastructure" / "local" / "caddy" / "Caddyfile"


def tunnel_site() -> str:
    text = CADDYFILE.read_text(encoding="utf-8")
    start = text.index("http://:8088 {")
    depth, end = 0, start
    for end in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[end], 0)
        if depth == 0 and text[end] == "}":
            break
    return text[start : end + 1]


def test_the_phone_tunnel_hands_the_api_a_host_it_answers_to() -> None:
    site = tunnel_site()
    proxies = re.findall(r"reverse_proxy (host\.docker\.internal:8000)(\s*\{[^}]*\})?", site)
    assert len(proxies) == 2, "redeem and rejoin go to the API"
    for upstream, options in proxies:
        assert "header_up Host {upstream_hostport}" in options, options
        assert upstream.split(":")[0] in ApiSettings().hosts
