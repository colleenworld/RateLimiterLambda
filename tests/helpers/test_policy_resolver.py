from decimal import Decimal
from unittest.mock import Mock

import pytest

import helpers.policy_resolver as policy_resolver


@pytest.fixture(autouse=True)
def reset_resolver_state():
    policy_resolver._cache.clear()
    policy_resolver._table = None


def test_returns_token_bucket_policy(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {
        "Item": {
            "policy_id": "standard",
            "algorithm": "token_bucket_v1",
            "capacity": Decimal("20"),
            "refill_rate": Decimal("2.5"),
            "enabled": True,
            "policy_version": Decimal("3"),
        }
    }

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    policy = policy_resolver.get_policy(
        "standard"
    )

    assert policy.policy_id == "standard"
    assert policy.algorithm == "token_bucket_v1"
    assert policy.capacity == 20
    assert policy.refill_rate == 2.5
    assert policy.window_ms is None
    assert policy.enabled is True
    assert policy.version == 3

    table.get_item.assert_called_once_with(
        Key={
            "policy_id": "standard",
        }
    )


def test_returns_fixed_window_policy(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {
        "Item": {
            "policy_id": "fixed",
            "algorithm": "fixed_window_v1",
            "capacity": Decimal("100"),
            "window_ms": Decimal("60000"),
        }
    }

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    policy = policy_resolver.get_policy(
        "fixed"
    )

    assert policy.policy_id == "fixed"
    assert policy.algorithm == "fixed_window_v1"
    assert policy.capacity == 100
    assert policy.window_ms == 60_000
    assert policy.refill_rate is None
    assert policy.enabled is True
    assert policy.version == 1


def test_returns_sliding_window_policy(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {
        "Item": {
            "policy_id": "sliding",
            "algorithm": "sliding_window_v1",
            "capacity": Decimal("50"),
            "window_ms": Decimal("10000"),
        }
    }

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    policy = policy_resolver.get_policy(
        "sliding"
    )

    assert policy.policy_id == "sliding"
    assert policy.algorithm == "sliding_window_v1"
    assert policy.capacity == 50
    assert policy.window_ms == 10_000
    assert policy.refill_rate is None


def test_defaults_algorithm_to_token_bucket(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {
        "Item": {
            "policy_id": "default-algorithm",
            "capacity": Decimal("20"),
            "refill_rate": Decimal("2"),
        }
    }

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    policy = policy_resolver.get_policy(
        "default-algorithm"
    )

    assert policy.algorithm == "token_bucket_v1"


def test_uses_default_enabled_and_version(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {
        "Item": {
            "policy_id": "defaults",
            "algorithm": "token_bucket_v1",
            "capacity": Decimal("20"),
            "refill_rate": Decimal("2"),
        }
    }

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    policy = policy_resolver.get_policy(
        "defaults"
    )

    assert policy.enabled is True
    assert policy.version == 1


def test_preserves_disabled_policy(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {
        "Item": {
            "policy_id": "disabled",
            "algorithm": "token_bucket_v1",
            "capacity": Decimal("20"),
            "refill_rate": Decimal("2"),
            "enabled": False,
        }
    }

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    policy = policy_resolver.get_policy(
        "disabled"
    )

    assert policy.enabled is False


def test_uses_cache(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {
        "Item": {
            "policy_id": "cached",
            "algorithm": "token_bucket_v1",
            "capacity": Decimal("20"),
            "refill_rate": Decimal("2"),
        }
    }

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    first = policy_resolver.get_policy(
        "cached"
    )

    second = policy_resolver.get_policy(
        "cached"
    )

    assert first is second

    table.get_item.assert_called_once()


def test_missing_policy_raises_key_error(
    monkeypatch,
):
    table = Mock()

    table.get_item.return_value = {}

    monkeypatch.setattr(
        policy_resolver,
        "get_table",
        lambda: table,
    )

    with pytest.raises(
        KeyError,
        match="Rate-limit policy not found",
    ):
        policy_resolver.get_policy(
            "missing"
        )