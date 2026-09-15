import json

from app.core import onboarding


def test_fresh_install_requires_setup(tmp_path, monkeypatch):
    state_path = tmp_path / "setup-state.json"
    config_path = tmp_path / "workflows-config.json"
    monkeypatch.setattr(onboarding, "SETUP_STATE_PATH", str(state_path))
    monkeypatch.setattr(onboarding, "USER_CONFIG_PATH", str(config_path))

    onboarding.initialize_setup_state(was_fresh_install=True)
    state = json.loads(state_path.read_text())

    assert state["complete"] is False
    assert onboarding.setup_required() is True


def test_existing_install_is_migrated_as_complete(tmp_path, monkeypatch):
    state_path = tmp_path / "setup-state.json"
    config_path = tmp_path / "workflows-config.json"
    config_path.write_text("{}")
    monkeypatch.setattr(onboarding, "SETUP_STATE_PATH", str(state_path))
    monkeypatch.setattr(onboarding, "USER_CONFIG_PATH", str(config_path))

    onboarding.initialize_setup_state(was_fresh_install=False)
    state = json.loads(state_path.read_text())

    assert state["complete"] is True
    assert state["migratedExistingInstall"] is True
    assert onboarding.setup_required() is False


def test_mark_setup_complete(tmp_path, monkeypatch):
    state_path = tmp_path / "setup-state.json"
    config_path = tmp_path / "workflows-config.json"
    monkeypatch.setattr(onboarding, "SETUP_STATE_PATH", str(state_path))
    monkeypatch.setattr(onboarding, "USER_CONFIG_PATH", str(config_path))

    onboarding.initialize_setup_state(was_fresh_install=True)
    onboarding.mark_setup_complete()

    assert onboarding.setup_required() is False
