from pathlib import Path

import pytest
from pydantic import ValidationError

from hirevion_interview_agent.settings import AgentSettings

GEMINI = "gemini-test-" + "g" * 30
DEEPGRAM = "deepgram-test-" + "d" * 30
LIVEKIT_SECRET = "livekit-test-" + "l" * 30


def write_env(path: Path, **values: str) -> Path:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GEMINI_API_KEY", "DEEPGRAM_API_KEY", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(name, raising=False)


def test_settings_load_from_env_file_with_defaults(tmp_path: Path) -> None:
    env = write_env(
        tmp_path / ".env",
        GEMINI_API_KEY=GEMINI,
        DEEPGRAM_API_KEY=DEEPGRAM,
        LIVEKIT_API_KEY="hirevion-local",
        LIVEKIT_API_SECRET=LIVEKIT_SECRET,
        HV_TTS_VOICE="aura-2-test-en",
    )
    settings = AgentSettings(_env_file=env)
    assert settings.gemini_api_key.get_secret_value() == GEMINI
    assert settings.livekit_url == "ws://127.0.0.1:7880"
    assert settings.hv_llm_base_url.startswith("https://generativelanguage.googleapis.com/")
    assert settings.hv_tts_voice == "aura-2-test-en"
    assert settings.hv_turn_detection == "vad"


def test_secrets_never_appear_in_repr(tmp_path: Path) -> None:
    env = write_env(
        tmp_path / ".env",
        GEMINI_API_KEY=GEMINI,
        DEEPGRAM_API_KEY=DEEPGRAM,
        LIVEKIT_API_KEY="hirevion-local",
        LIVEKIT_API_SECRET=LIVEKIT_SECRET,
    )
    text = repr(AgentSettings(_env_file=env))
    assert GEMINI not in text
    assert DEEPGRAM not in text
    assert LIVEKIT_SECRET not in text


def test_missing_key_is_named_without_values(tmp_path: Path) -> None:
    env = write_env(
        tmp_path / ".env",
        DEEPGRAM_API_KEY=DEEPGRAM,
        LIVEKIT_API_KEY="hirevion-local",
        LIVEKIT_API_SECRET=LIVEKIT_SECRET,
    )
    with pytest.raises(ValidationError) as error:
        AgentSettings(_env_file=env)
    message = str(error.value)
    assert "gemini_api_key" in message
    assert DEEPGRAM not in message


def test_turn_detection_rejects_unknown_modes(tmp_path: Path) -> None:
    env = write_env(
        tmp_path / ".env",
        GEMINI_API_KEY=GEMINI,
        DEEPGRAM_API_KEY=DEEPGRAM,
        LIVEKIT_API_KEY="hirevion-local",
        LIVEKIT_API_SECRET=LIVEKIT_SECRET,
        HV_TURN_DETECTION="telepathy",
    )
    with pytest.raises(ValidationError):
        AgentSettings(_env_file=env)


def test_preemptive_generation_is_off_unless_enabled(tmp_path: Path) -> None:
    base = {
        "GEMINI_API_KEY": GEMINI,
        "DEEPGRAM_API_KEY": DEEPGRAM,
        "LIVEKIT_API_KEY": "hirevion-local",
        "LIVEKIT_API_SECRET": LIVEKIT_SECRET,
    }
    assert (
        AgentSettings(_env_file=write_env(tmp_path / "a.env", **base)).hv_preemptive_generation
        is False
    )
    enabled = write_env(tmp_path / "b.env", **base, HV_PREEMPTIVE_GENERATION="true")
    assert AgentSettings(_env_file=enabled).hv_preemptive_generation is True


def test_max_sessions_defaults_to_ten_and_must_be_positive(tmp_path: Path) -> None:
    base = {
        "GEMINI_API_KEY": GEMINI,
        "DEEPGRAM_API_KEY": DEEPGRAM,
        "LIVEKIT_API_KEY": "hirevion-local",
        "LIVEKIT_API_SECRET": LIVEKIT_SECRET,
    }
    assert (
        AgentSettings(_env_file=write_env(tmp_path / "a.env", **base)).hv_agent_max_sessions == 10
    )
    with pytest.raises(ValidationError):
        AgentSettings(_env_file=write_env(tmp_path / "b.env", **base, HV_AGENT_MAX_SESSIONS="0"))
