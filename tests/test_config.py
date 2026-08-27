"""Tests: settings service and provider registry (free-first ordering)."""

from __future__ import annotations

import json
import os

from ai_video_factory.config.providers import (
    ProviderKind,
    ProviderTier,
    default_chain,
    get_provider_info,
    providers_for,
)
from ai_video_factory.config.settings import AppSettings, SettingsService


def test_defaults_create_managed_dirs(tmp_path):
    settings = AppSettings.defaults(root=tmp_path)
    settings.ensure_directories()
    assert settings.projects_dir == tmp_path / "projects"
    assert settings.database_path == tmp_path / "data" / "avf.sqlite3"
    assert settings.projects_dir.exists()
    assert settings.demo_mode is True
    assert settings.providers.llm == "demo"


def test_settings_service_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("AVF_DEMO_MODE", raising=False)
    service = SettingsService(config_file=tmp_path / "conf.json", env_file=tmp_path / "no.env", root=tmp_path)
    assert service.settings.demo_mode is True

    service.update(demo_mode=False, language="en")
    assert service.settings.demo_mode is False

    # Reload from disk — persistence verified.
    reloaded = SettingsService(config_file=tmp_path / "conf.json", env_file=tmp_path / "no.env", root=tmp_path)
    assert reloaded.settings.demo_mode is False
    assert reloaded.settings.language == "en"
    assert json.loads((tmp_path / "conf.json").read_text(encoding="utf-8"))["language"] == "en"


def test_env_overrides_beat_file(tmp_path, monkeypatch):
    config_file = tmp_path / "conf.json"
    config_file.write_text(json.dumps({"demo_mode": True}), encoding="utf-8")
    monkeypatch.setenv("AVF_DEMO_MODE", "false")
    service = SettingsService(config_file=config_file, env_file=tmp_path / "no.env", root=tmp_path)
    assert service.settings.demo_mode is False


def test_corrupt_settings_file_falls_back_to_defaults(tmp_path):
    config_file = tmp_path / "conf.json"
    config_file.write_text("{broken json", encoding="utf-8")
    service = SettingsService(config_file=config_file, env_file=tmp_path / "no.env", root=tmp_path)
    assert service.settings.language == "ar"  # default intact


def test_provider_registry_free_first_order():
    llm_chain = default_chain(ProviderKind.LLM)
    assert llm_chain[0] == "demo"           # local demo first
    assert llm_chain[1] == "ollama"         # local
    assert "openai" == llm_chain[-1]        # paid last
    for kind in ProviderKind:
        tiers = [info.tier for info in providers_for(kind)]
        order = {"local": 0, "free": 1, "paid": 2}
        assert tiers == sorted(tiers, key=lambda tier: order[tier.value])


def test_get_provider_info_lookup_and_errors():
    info = get_provider_info(ProviderKind.LLM, "ollama")
    assert info.tier == ProviderTier.LOCAL
    assert info.endpoint_env == "OLLAMA_BASE_URL"
    try:
        get_provider_info(ProviderKind.LLM, "does-not-exist")
        raised = False
    except KeyError:
        raised = True
    assert raised
