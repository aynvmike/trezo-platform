"""Settings knobs are BOUND (audit 2026-09-01, rv:bound-hunter MAJOR on
app/config.py + Wave 1 not_done).

The house failure mode is BUILT BUT NOT BOUND. Two readers were built
"Settings first": options_scanner._lane_enabled (TREZO_DAY_OPTIONS /
TREZO_SPREADS / TREZO_LONG_OPTIONS) and reevaluator._settings_num /
_settings_flag (the G19 numeric tunables). Both do
`getattr(get_settings(), attr, None)` -- and app/config.py declared none
of those attrs with `extra="ignore"`, so the getattr was always None, a
value in agents/.env was silently dropped, and the read fell through to
os.getenv, which never sees agents/.env.

These guards pin the binding from BOTH ends without booting the engine
or reading a .env:

  * the real app/config.py (parsed, and loaded as a pydantic class under
    a private name -- never instantiated, so no .env is read) declares
    every attribute the two readers ask for, by exact name, with the
    exact default the reader used to fall back to;
  * the REAL reader code paths honour a declared value (driven through
    the gate's credential-free app.config stub, patched and restored);
  * .env.example documents every new key name.

Plain zero-arg test_ functions, no pytest, no network, no .env.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import os
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
reeval = load_module("app.agents.reevaluator")
scanner = load_module("app.agents.options_scanner")

AGENTS_DIR = Path(__file__).resolve().parents[1]
CONFIG_PY = AGENTS_DIR / "app" / "config.py"
REEVAL_PY = AGENTS_DIR / "app" / "agents" / "reevaluator.py"
ENV_EXAMPLE = AGENTS_DIR.parent / ".env.example"

LANE_SWITCHES = ("trezo_day_options", "trezo_spreads", "trezo_long_options")
# Inline reevaluator reads that are not in _TUNABLES (attr, default).
REEVAL_INLINE = {
    "trezo_reeval_tcs_collapse_frac": 0.5,
    "trezo_reeval_shadow_far_pct": 0.03,
    "trezo_reeval_tcs_rescore": True,
}


def _declared_defaults() -> dict[str, object]:
    """name -> literal default for every annotated field of Settings,
    straight from the source (no import, no instantiation)."""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "Settings")
    out: dict[str, object] = {}
    for n in cls.body:
        if (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                and n.value is not None):
            out[n.target.id] = ast.literal_eval(n.value)
    return out


def _real_settings_class():
    """The real pydantic Settings CLASS from app/config.py, loaded under a
    private module name so the gate's app.config stub is untouched. The
    class is never instantiated (that would read agents/.env)."""
    spec = importlib.util.spec_from_file_location("_trezo_real_config", CONFIG_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Settings


@contextlib.contextmanager
def _patched(obj, **attrs):
    """Swap attributes on a module/object and ALWAYS put them back."""
    missing = object()
    saved = {k: getattr(obj, k, missing) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in saved.items():
            if v is missing:
                delattr(obj, k)
            else:
                setattr(obj, k, v)


def _reeval_attrs_asked_for() -> set[str]:
    """Every Settings attr the reevaluator source asks for by name."""
    src = REEVAL_PY.read_text(encoding="utf-8")
    return set(re.findall(r"[\"'](trezo_reeval_[a-z_]+)[\"']", src))


# --- declarations ------------------------------------------------------------

def test_lane_switches_are_declared_and_default_off():
    d = _declared_defaults()
    for name in LANE_SWITCHES:
        assert name in d, f"config.py does not declare {name}; _lane_enabled has nothing to read"
        assert d[name] is False, f"{name} must default OFF (was {d[name]!r})"


def test_dividend_lane_switch_is_declared_dark():
    d = _declared_defaults()
    assert d.get("trezo_dividend_lt_tcs") == 0, (
        "trezo_dividend_lt_tcs must be declared with default 0 (lane emits no tcs)")


def test_every_reevaluator_tunable_is_declared_with_its_exact_default():
    d = _declared_defaults()
    for key, (attr, env, default) in reeval._TUNABLES.items():
        assert attr in d, f"config.py does not declare {attr} ({key}/{env})"
        assert float(d[attr]) == float(default), (
            f"{attr}: config default {d[attr]!r} != reevaluator default {default!r}")
    for attr, default in REEVAL_INLINE.items():
        assert attr in d, f"config.py does not declare {attr}"
        assert d[attr] == default, f"{attr}: {d[attr]!r} != {default!r}"


def test_no_reevaluator_settings_read_is_left_undeclared():
    """The binding check from the READER's side: any trezo_reeval_* name
    the reevaluator source asks for must exist on Settings."""
    d = _declared_defaults()
    asked = _reeval_attrs_asked_for()
    assert asked, "regex found no trezo_reeval_* reads; the guard is broken"
    undeclared = sorted(a for a in asked if a not in d)
    assert not undeclared, f"reevaluator reads undeclared Settings attrs: {undeclared}"


def test_real_pydantic_settings_class_carries_the_fields():
    """pydantic must accept the declarations (a bad annotation would raise
    here, at class creation, long before any engine boot)."""
    Settings = _real_settings_class()
    fields = Settings.model_fields
    want = set(LANE_SWITCHES) | {"trezo_dividend_lt_tcs"} | set(REEVAL_INLINE) \
        | {attr for attr, _e, _d in reeval._TUNABLES.values()}
    missing = sorted(w for w in want if w not in fields)
    assert not missing, f"Settings.model_fields lacks {missing}"
    for name in LANE_SWITCHES:
        assert fields[name].default is False
    assert fields["trezo_dividend_lt_tcs"].default == 0
    assert float(fields["trezo_reeval_cooldown_sec"].default) == 900.0


# --- the real reader code paths honour a declared value ---------------------

def test_reevaluator_tunable_reads_the_declared_settings_attr():
    for env in ("TREZO_REEVAL_COOLDOWN_SEC", "TREZO_REEVAL_STALE_DAYS"):
        assert os.getenv(env) is None, f"{env} set in this shell; test env is dirty"
    cfg = sys.modules["app.config"]
    d = _declared_defaults()
    # With the declared defaults on the settings object -> the same numbers
    # the reevaluator used to fall back to, now coming FROM Settings.
    with _patched(cfg, get_settings=lambda: types.SimpleNamespace(**d)):
        assert reeval.tunable("COOLDOWN_SEC") == 900.0
        assert reeval.tunable("STALE_DAYS") == 3.0
        assert reeval._settings_num("trezo_reeval_tcs_collapse_frac",
                                    "TREZO_REEVAL_TCS_COLLAPSE_FRAC", 0.5) == 0.5
        assert reeval._settings_flag("trezo_reeval_tcs_rescore",
                                     "TREZO_REEVAL_TCS_RESCORE", True) is True
    # An agents/.env override (a different value on Settings) is honoured
    # -- the whole point of declaring the field.
    over = dict(d, trezo_reeval_cooldown_sec=123, trezo_reeval_tcs_rescore=False)
    with _patched(cfg, get_settings=lambda: types.SimpleNamespace(**over)):
        assert reeval.tunable("COOLDOWN_SEC") == 123.0
        assert reeval._settings_flag("trezo_reeval_tcs_rescore",
                                     "TREZO_REEVAL_TCS_RESCORE", True) is False
    # Restored: back to the fallback path.
    assert reeval.tunable("COOLDOWN_SEC") == 900.0


def test_options_lane_switch_reads_the_declared_settings_attr():
    for env in ("TREZO_DAY_OPTIONS", "TREZO_SPREADS", "TREZO_LONG_OPTIONS"):
        assert os.getenv(env) is None, f"{env} set in this shell; test env is dirty"
    d = _declared_defaults()
    # Declared defaults -> every lane OFF, from Settings, no env fallthrough.
    with _patched(scanner, get_settings=lambda: types.SimpleNamespace(**d)):
        for env in ("TREZO_DAY_OPTIONS", "TREZO_SPREADS", "TREZO_LONG_OPTIONS"):
            assert scanner._lane_enabled(env) is False
    # Flip ONE in "agents/.env" (i.e. on Settings) -> that lane only.
    with _patched(scanner, get_settings=lambda: types.SimpleNamespace(**dict(d, trezo_spreads=True))):
        assert scanner._lane_enabled("TREZO_SPREADS") is True
        assert scanner._lane_enabled("TREZO_DAY_OPTIONS") is False
        assert scanner._lane_enabled("TREZO_LONG_OPTIONS") is False
    assert scanner._lane_enabled("TREZO_SPREADS") is False


# --- operator surface --------------------------------------------------------

def test_env_example_documents_every_new_key():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    names = set(LANE_SWITCHES) | {"trezo_dividend_lt_tcs"} | set(REEVAL_INLINE) \
        | {attr for attr, _e, _d in reeval._TUNABLES.values()}
    missing = sorted(n.upper() for n in names
                     if not re.search(rf"^{n.upper()}=", text, re.M))
    assert not missing, f".env.example lacks {missing}"
    assert "TREZO_DIVIDEND_LT_TCS" in text and "ON-SWITCH" in text.upper()


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
