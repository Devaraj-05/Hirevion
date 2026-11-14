import base64
from pathlib import Path

from hirevion_devcli.envfile import (
    GENERATED_BASE64_KEYS,
    GENERATED_KEYS,
    generate_local_secrets,
    init_env,
    is_placeholder,
    missing_required,
    parse_env,
    render_env,
    sync_env,
)


def test_parse_env_skips_comments_and_strips_quotes() -> None:
    text = "# comment\n\nA=1\nexport B='two'\nC=\"three\"\nNOT_A_PAIR\nD=\n"
    assert parse_env(text) == {"A": "1", "B": "two", "C": "three", "D": ""}


def test_placeholders_are_detected() -> None:
    assert is_placeholder("")
    assert is_placeholder("  ")
    assert is_placeholder("changeme")
    assert is_placeholder("<your key>")
    assert is_placeholder("your-openai-key")
    assert not is_placeholder("real-value-" + "9" * 30)


def test_missing_required_lists_empty_and_placeholder_keys() -> None:
    values = {
        "OPENROUTER_API_KEY": "changeme",
        "nemotron_API_KEY": "n" * 40,  # names count in any case
        "DEEPGRAM_API_KEY": "k" * 40,
    }
    assert missing_required(values) == ["OPENROUTER_API_KEY"]
    assert missing_required({}) == ["OPENROUTER_API_KEY", "NEMOTRON_API_KEY", "DEEPGRAM_API_KEY"]


def test_sync_env_appends_only_missing_keys() -> None:
    example = "A=\nB=default\nPOSTGRES_PASSWORD=\nC=\n"
    env = "A=mine\n"
    new_text, added = sync_env(example, env, {"POSTGRES_PASSWORD": "p" * 32})
    assert added == ["B", "POSTGRES_PASSWORD", "C"]
    assert parse_env(new_text) == {
        "A": "mine",
        "B": "default",
        "POSTGRES_PASSWORD": "p" * 32,
        "C": "",
    }
    assert new_text.startswith("A=mine\n")


def test_sync_env_is_a_no_op_when_complete() -> None:
    env = "A=mine\nB=x\n"
    assert sync_env("A=\nB=\n", env, {}) == (env, [])


def test_sync_env_handles_env_without_trailing_newline() -> None:
    new_text, added = sync_env("A=\nB=\n", "A=mine", {})
    assert added == ["B"]
    assert parse_env(new_text) == {"A": "mine", "B": ""}


def test_generated_secrets_are_random_and_long_enough() -> None:
    first = generate_local_secrets()
    second = generate_local_secrets()
    assert set(first) == set(GENERATED_KEYS) | set(GENERATED_BASE64_KEYS) | {
        "HV_CANDIDATE_TOKEN_KEY"
    }
    for key, length in GENERATED_KEYS.items():
        assert len(first[key]) == length
        assert first[key] != second[key]
    for key, size in GENERATED_BASE64_KEYS.items():
        assert len(base64.b64decode(first[key], validate=True)) == size
        assert first[key] != second[key]


def test_render_env_fills_only_empty_generated_keys() -> None:
    example = "# c\nPOSTGRES_PASSWORD=\nLIVEKIT_API_SECRET=keep\nOPENAI_API_KEY=\n"
    rendered = render_env(example, {"POSTGRES_PASSWORD": "p" * 32, "LIVEKIT_API_SECRET": "s" * 48})
    assert parse_env(rendered) == {
        "POSTGRES_PASSWORD": "p" * 32,
        "LIVEKIT_API_SECRET": "keep",
        "OPENAI_API_KEY": "",
    }
    assert rendered.startswith("# c\n")


def test_init_env_creates_file_once(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("POSTGRES_PASSWORD=\nOPENAI_API_KEY=\n", encoding="utf-8")
    env = tmp_path / ".env"
    assert init_env(example, env) is True
    created = env.read_text(encoding="utf-8")
    assert len(parse_env(created)["POSTGRES_PASSWORD"]) == GENERATED_KEYS["POSTGRES_PASSWORD"]
    assert init_env(example, env) is False
    assert env.read_text(encoding="utf-8") == created


def test_generates_passwords_for_the_database_roles() -> None:
    generated = generate_local_secrets()
    for key in ("POSTGRES_APP_PASSWORD", "POSTGRES_RELAY_PASSWORD"):
        assert len(generated[key]) == 32
        assert generated[key].replace("-", "").replace("_", "").isalnum()


def test_a_seed_password_is_generated_long_enough_for_the_policy() -> None:
    # Sign-in passwords need 15 characters until MFA arrives (SP-02 spec).
    assert len(generate_local_secrets()["HV_SEED_PASSWORD"]) >= 15


def test_the_candidate_token_key_is_a_p256_signing_key() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    der = base64.b64decode(generate_local_secrets()["HV_CANDIDATE_TOKEN_KEY"], validate=True)
    key = serialization.load_der_private_key(der, password=None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    assert isinstance(key.curve, ec.SECP256R1)


def test_sync_env_matches_names_in_any_case() -> None:
    # The settings read names in any case, so a key written as `nemotron_API_KEY` is the
    # example's NEMOTRON_API_KEY: appending an empty copy after it would override its value.
    example = "NEMOTRON_API_KEY=\nOPENROUTER_API_KEY=\nHV_NEW=1\n"
    env = "nemotron_API_KEY=n-key\nOpenRouter_API_KEY=o-key\n"
    text, added = sync_env(example, env, {})
    assert added == ["HV_NEW"]
    assert text.count("API_KEY") == 2


def test_the_required_keys_follow_the_routes() -> None:
    """Only the providers the routes use need keys (ADR-0034); Deepgram always does."""
    by_openrouter = {
        "HV_AI_INTERVIEW_PROVIDER": "openrouter",
        "OPENROUTER_API_KEY": "o" * 40,
        "DEEPGRAM_API_KEY": "d" * 40,
    }
    assert missing_required(by_openrouter) == []
    assert missing_required({"hv_ai_screening_provider": "gemini"}) == [
        "GEMINI_API_KEY",
        "NEMOTRON_API_KEY",
        "DEEPGRAM_API_KEY",
    ]
