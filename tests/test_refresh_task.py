"""Test the refresh task with and without Home Assistant installed."""

import asyncio
import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest
from ta_cmi import ApiError

MODULE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ta_coe" / "refresh_task.py"
)

try:
    from custom_components.ta_coe.refresh_task import RefreshTask
except ImportError:
    if "custom_components.ta_coe" not in sys.modules:
        package = types.ModuleType("custom_components.ta_coe")
        package.__path__ = [str(MODULE_PATH.parent)]
        sys.modules["custom_components.ta_coe"] = package
    if "custom_components.ta_coe.const" not in sys.modules:
        const = types.ModuleType("custom_components.ta_coe.const")
        const._LOGGER = logging.getLogger("ta_coe")
        sys.modules["custom_components.ta_coe.const"] = const
    spec = importlib.util.spec_from_file_location(
        "custom_components.ta_coe.refresh_task", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    RefreshTask = module.RefreshTask


@pytest.fixture
def real_sleep(monkeypatch):
    """Run refresh waits without delaying the tests."""
    original_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda seconds: original_sleep(0))
    return original_sleep


class FailingSender:
    """Sender whose API call always fails."""

    def __init__(self):
        self.calls = 0

    def has_entities(self):
        return True

    async def update(self):
        self.calls += 1
        raise ApiError("server unavailable")


def test_loop_survives_api_error(real_sleep):
    """An API error must not kill the periodic refresh loop."""
    async def run():
        sender = FailingSender()
        task = RefreshTask(sender)
        await task.start()
        await real_sleep(0.05)
        assert task.is_started
        assert sender.calls >= 2
        await task.stop()

    asyncio.run(run())


def test_stop_after_dead_task_does_not_raise(real_sleep):
    """Stopping a task that already failed must be harmless."""
    async def run():
        sender = FailingSender()
        task = RefreshTask(sender)
        await task.start()
        await real_sleep(0.05)
        await task.stop()
        assert not task.is_started

    asyncio.run(run())
