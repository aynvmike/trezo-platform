"""Load one runtime module without booting the whole agent runtime.

`app/runtime/__init__.py` wires the bus, the registry, the scheduler and
the agent base class together, so a plain `from app.runtime import
book_scope` drags in most of the platform -- and a guard test that needs
the platform to start is a guard test nobody runs.

These loaders register a stub package and exec the single module under
test straight from its file, so the guards run in a bare checkout: in a
pre-commit hook, in CI, on a laptop with no .env and no broker keys.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parents[1]


def _stub_package(name: str, path: Path) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


def stub_config(**overrides) -> types.ModuleType:
    """Install a credential-free `app.config` BEFORE anything imports it.

    Several modules under test (`app.brokers.*`) read settings at import
    time, so on a machine without pydantic-settings or a .env the import
    dies and the guard never runs. Call this first in any test file that
    touches a broker module."""
    if "app.config" in sys.modules:
        return sys.modules["app.config"]
    _stub_package("app", AGENTS_DIR / "app")
    cfg = types.ModuleType("app.config")

    class _Settings:
        alpaca_api_key = "K" * 26
        alpaca_secret_key = "S" * 44
        alpaca_base_url = "https://paper-api.alpaca.markets"
        trezo_live_trading = False
        supabase_url = "https://stub.supabase.co"
        supabase_service_role_key = "stub"
        supabase_anon_key = "stub"

    for k, v in overrides.items():
        setattr(_Settings, k, v)
    cfg.get_settings = lambda: _Settings()
    cfg.settings = _Settings()
    sys.modules["app.config"] = cfg
    return cfg


def load_module(dotted: str) -> types.ModuleType:
    """load_module('app.runtime.book_scope') -> the module object."""
    if str(AGENTS_DIR) not in sys.path:
        sys.path.insert(0, str(AGENTS_DIR))
    if dotted in sys.modules:
        return sys.modules[dotted]
    parts = dotted.split(".")
    here = AGENTS_DIR
    for i in range(1, len(parts)):
        here = here / parts[i - 1]
        _stub_package(".".join(parts[:i]), here)
    target = AGENTS_DIR.joinpath(*parts).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(dotted, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {dotted} from {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    parent = sys.modules.get(".".join(parts[:-1]))
    if parent is not None:
        setattr(parent, parts[-1], mod)
    return mod


def run_tests(namespace: dict) -> int:
    """Tiny runner so these files work with or without pytest."""
    fails = 0
    for name, fn in sorted(namespace.items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {name}: {e}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if fails else 'all green'} ({fails} failures)")
    return 1 if fails else 0
