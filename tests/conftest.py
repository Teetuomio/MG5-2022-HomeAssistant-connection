"""Shared test setup.

With Home Assistant installed, the real integration package is imported and
the Home Assistant tests in tests/ha run. Without it, the package is
registered without running its init, so the decoding and command tests still
run on a plain Python install.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

if importlib.util.find_spec("homeassistant") is None:
    _COMPONENTS = _ROOT / "custom_components"
    _parent = types.ModuleType("custom_components")
    _parent.__path__ = [str(_COMPONENTS)]
    sys.modules["custom_components"] = _parent

    _package = types.ModuleType("custom_components.mg5")
    _package.__path__ = [str(_COMPONENTS / "mg5")]
    _package.__package__ = "custom_components.mg5"
    sys.modules["custom_components.mg5"] = _package

    collect_ignore = ["ha"]
elif str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def run():
    """Run a coroutine on a private loop.

    asyncio.run() unsets the thread's event loop afterwards, which breaks the
    Home Assistant plugin's fixtures for every test that follows.
    """

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return _run
