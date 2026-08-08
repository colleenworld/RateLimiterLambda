from unittest.mock import Mock

import pytest

import classes.script_registry as script_registry_module
from classes.errors import ConfigurationError
from classes.script_registry import ScriptRegistry


def test_loads_and_registers_script(monkeypatch):
    client = Mock()
    registered_script = Mock()

    client.register_script.return_value = registered_script

    monkeypatch.setattr(
        script_registry_module.Path,
        "read_text",
        lambda _self, encoding=None: "return {1, 10}",
    )

    registry = ScriptRegistry(client)

    result = registry.get("token_bucket_v1")

    client.register_script.assert_called_once_with(
        "return {1, 10}"
    )

    assert result is registered_script


def test_caches_loaded_script(monkeypatch):
    client = Mock()
    registered_script = Mock()

    client.register_script.return_value = registered_script

    monkeypatch.setattr(
        script_registry_module.Path,
        "read_text",
        lambda _self, encoding=None: "return {1, 10}",
    )

    registry = ScriptRegistry(client)

    first = registry.get("token_bucket_v1")
    second = registry.get("token_bucket_v1")

    assert first is registered_script
    assert second is registered_script

    client.register_script.assert_called_once()


def test_loads_different_scripts_separately(
    monkeypatch,
):
    client = Mock()

    token_script = Mock()
    fixed_script = Mock()

    client.register_script.side_effect = [
        token_script,
        fixed_script,
    ]

    def fake_read_text(path, encoding=None):
        if path.name == "token_bucket_v1.lua":
            return "token bucket lua"

        if path.name == "fixed_window_v1.lua":
            return "fixed window lua"

        raise AssertionError(
            f"Unexpected file: {path.name}"
        )

    monkeypatch.setattr(
        script_registry_module.Path,
        "read_text",
        fake_read_text,
    )

    registry = ScriptRegistry(client)

    result1 = registry.get("token_bucket_v1")
    result2 = registry.get("fixed_window_v1")

    assert result1 is token_script
    assert result2 is fixed_script

    assert client.register_script.call_count == 2


def test_unknown_algorithm_raises_configuration_error():
    registry = ScriptRegistry(Mock())

    with pytest.raises(
        ConfigurationError,
        match="Unknown rate-limit algorithm",
    ):
        registry.get("not_real")


def test_missing_script_raises_configuration_error(
    monkeypatch,
):
    client = Mock()

    def raise_file_not_found(
        _self,
        encoding=None,
    ):
        raise FileNotFoundError(
            "script not found"
        )

    monkeypatch.setattr(
        script_registry_module.Path,
        "read_text",
        raise_file_not_found,
    )

    registry = ScriptRegistry(client)

    with pytest.raises(
        ConfigurationError,
        match="Unable to load Lua script",
    ):
        registry.get("token_bucket_v1")