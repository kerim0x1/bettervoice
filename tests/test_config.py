import os

from bettervoice import config


def test_defaults(settings):
    assert settings.get("language") == config.AUTO
    assert settings.get("local_model") == config.LOCAL_AUTO
    assert settings.get("engine") == config.LOCAL  # nothing configured: offline works
    assert not settings.enabled("polish")


def test_set_persists_and_replaces(settings):
    settings.set("language", "de")
    settings.set("language", "fr")
    settings.set("openrouter_key", "sk-or-1")
    lines = open(settings.CONFIG_ENV, encoding="utf-8").read().splitlines()
    assert lines.count("DICTATE_LANGUAGE=fr") == 1
    assert not any(line.startswith("DICTATE_LANGUAGE=de") for line in lines)
    assert "OPENROUTER_API_KEY=sk-or-1" in lines
    assert settings.get("language") == "fr"


def test_legacy_values(settings, monkeypatch):
    # before ElevenLabs/OpenRouter, "cloud" meant Deepgram
    monkeypatch.setenv("DICTATE_ENGINE", "cloud")
    assert settings.get("engine") == config.DEEPGRAM
    # an existing Deepgram key keeps an old install on Deepgram
    monkeypatch.delenv("DICTATE_ENGINE")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg")
    assert settings.get("engine") == config.DEEPGRAM
    # DICTATE_MODEL was the Deepgram model's old name
    monkeypatch.setenv("DICTATE_MODEL", "nova-2")
    assert settings.get("deepgram_model") == "nova-2"
    settings.set("deepgram_model", "nova-3")
    assert "DICTATE_MODEL" not in os.environ
    assert settings.get("deepgram_model") == "nova-3"


def test_unknown_engine_falls_back(settings, monkeypatch):
    monkeypatch.setenv("DICTATE_ENGINE", "nonsense")
    assert settings.get("engine") == config.LOCAL


def test_has_key(settings, monkeypatch):
    assert settings.has_key(config.LOCAL)
    assert not settings.has_key(config.ELEVENLABS)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "xi")
    assert settings.has_key(config.ELEVENLABS)


def test_env_file_parsing(settings, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("\ufeff# comment\nDICTATE_LANGUAGE=de   # inline comment\n"
                   "DEEPGRAM_API_KEY=paste_your_key_here\n", encoding="utf-8")
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path / "nowhere"))
    config._load_env()
    assert settings.get("language") == "de"
    assert settings.get("deepgram_key") == ""  # the placeholder isn't a key


def test_join_transcripts():
    assert config.join_transcripts(["Hello.", " World ", ""]) == "Hello. World"
    assert config.join_transcripts(["你好。", "今天天气很好。"]) == "你好。今天天气很好。"
    assert config.join_transcripts(["これはテストです。", "OK"]) == "これはテストです。OK"
    assert config.join_transcripts([]) == ""
