from app.core import settings


def test_settings_read_the_project_root_env_file():
    assert settings.PROJECT_ENV_FILE == settings.PROJECT_ROOT / ".env"
    assert settings.Settings.model_config["env_file"] == settings.PROJECT_ENV_FILE


def test_local_environment_does_not_override_exported_values(monkeypatch):
    calls: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        settings,
        "load_dotenv",
        lambda path, *, override: calls.append((path, override)),
    )

    settings.load_local_environment()

    assert calls == [(settings.PROJECT_ENV_FILE, False)]
