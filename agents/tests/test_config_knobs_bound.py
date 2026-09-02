"""Settings knobs are BOUND (audit 2026-09-01, rv:bound-hunter MAJOR on
app/config.py + Wave 1 not_done) -- and the template that documents them
is BOOT-SAFE (skeptic vf:config-web, same day).

The house failure mode is BUILT BUT NOT BOUND. Two readers were built
"Settings first": options_scanner._lane_enabled (TREZO_DAY_OPTIONS /
TREZO_SPREADS / TREZO_LONG_OPTIONS) and reevaluator._settings_num /
_settings_flag (the G19 numeric tunables). Both do
`getattr(get_settings(), attr, None)` -- and app/config.py declared none
of those attrs with `extra="ignore"`, so the getattr was always None, a
value in agents/.env was silently dropped, and the read fell through to
os.getenv, which never sees agents/.env.

vf:config-web: declaring the 16 fields TYPED (int/bool/float) while
.env.example listed them as blank lines with inline "# comments" made the
template a boot trap -- pydantic-settings 2.5.2 raises ValidationError at
Settings() for a blank or "# comment" value, get_settings() runs at
import, so one pasted line stopped the whole engine. Fixed on both sides:
Settings ignores empty values (env_ignore_empty), 13 of the 16 fields are
Optional (None = "not set", every reader falls through to its code
default; the three order-placing lane switches stay an explicit
`bool = False`, pinned by test_options_scanner_bookbound), and the
template shows the keys commented out with the code default.

These guards pin the binding from BOTH ends without booting the engine
or reading agents/.env:

  * the real app/config.py (parsed, and loaded as a pydantic class under
    a private name) declares every attribute the readers ask for, by
    exact name, as Optional with default None;
  * the REAL reader code paths turn None into the exact code default and
    honour a declared value (driven through the gate's credential-free
    app.config stub, patched and restored);
  * the REAL Settings class constructs from the template copied verbatim
    AND from a file that carries every template key blank (the boot-safety
    property), reading ONLY that file -- never agents/.env or the shell;
  * .env.example documents every new key name and swallows no comment as
    a value.

Plain zero-arg test_ functions, no pytest, no network, no .env.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import os
import re
import sys
import tempfile
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
# The 16 knobs vf:config-web is about: 13 Optional (default None) plus the
# three lane switches, which stay `bool = False`.
OPTIONAL_KNOBS = ({"trezo_dividend_lt_tcs"} | set(REEVAL_INLINE)
                  | {attr for attr, _e, _d in reeval._TUNABLES.values()})
ALL_NEW_KNOBS = OPTIONAL_KNOBS | set(LANE_SWITCHES)
# A template key, set or commented out: `KEY=` / `# KEY=`.
_TEMPLATE_KEY = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", re.M)


def _declared_fields() -> dict[str, tuple[str, object]]:
    """name -> (annotation source, literal default) for every annotated
    field of Settings, straight from the source (no import, no
    instantiation)."""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "Settings")
    out: dict[str, tuple[str, object]] = {}
    for n in cls.body:
        if (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                and n.value is not None):
            out[n.target.id] = (ast.unparse(n.annotation),
                                ast.literal_eval(n.value))
    return out


def _declared_defaults() -> dict[str, object]:
    return {k: v for k, (_a, v) in _declared_fields().items()}


def _real_settings_class():
    """The real pydantic Settings CLASS from app/config.py, loaded under a
    private module name so the gate's app.config stub is untouched.
    Instantiate it ONLY through _FileOnly below."""
    spec = importlib.util.spec_from_file_location("_trezo_real_config", CONFIG_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Settings


def _file_only_settings_class():
    """The real Settings, restricted to ONE source: the _env_file handed
    to it. Neither the process environment nor agents/.env can feed it,
    so the boot-safety guards below test the template and nothing else
    (a stray TREZO_* export on a dev box must not colour the result)."""
    Settings = _real_settings_class()

    class _FileOnly(Settings):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings,
                                       env_settings, dotenv_settings,
                                       file_secret_settings):
            return (init_settings, dotenv_settings)

    return _FileOnly


def _template_keys() -> list[str]:
    keys = _TEMPLATE_KEY.findall(ENV_EXAMPLE.read_text(encoding="utf-8"))
    assert len(keys) > 100, f"template key scan found only {len(keys)} keys; the regex is broken"
    return sorted(set(keys))


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


def _assert_readers_answer_code_defaults(settings_obj) -> None:
    """Drive the REAL readers against `settings_obj` (a Settings, or a
    stand-in) and require every code default, from every fall-through."""
    cfg = sys.modules["app.config"]
    with _patched(cfg, get_settings=lambda: settings_obj):
        for key, (_attr, _env, default) in reeval._TUNABLES.items():
            assert reeval.tunable(key) == float(default), (key, reeval.tunable(key))
        assert reeval._settings_num("trezo_reeval_tcs_collapse_frac",
                                    "TREZO_REEVAL_TCS_COLLAPSE_FRAC", 0.5) == 0.5
        assert reeval._settings_num("trezo_reeval_shadow_far_pct",
                                    "TREZO_REEVAL_SHADOW_FAR_PCT", 0.03) == 0.03
        assert reeval._settings_flag("trezo_reeval_tcs_rescore",
                                     "TREZO_REEVAL_TCS_RESCORE", True) is True
    with _patched(scanner, get_settings=lambda: settings_obj):
        for env in ("TREZO_DAY_OPTIONS", "TREZO_SPREADS", "TREZO_LONG_OPTIONS"):
            assert scanner._lane_enabled(env) is False, env


# --- declarations ------------------------------------------------------------

def test_lane_switches_are_declared_bool_and_default_off():
    """An order-placing lane's default must READ as off in config.py, so
    these three stay `bool = False`; a blank value is boot-safe through
    env_ignore_empty (pinned below), not through Optional."""
    f = _declared_fields()
    for name in LANE_SWITCHES:
        assert name in f, f"config.py does not declare {name}; _lane_enabled has nothing to read"
        ann, default = f[name]
        assert ann == "bool", f"{name}: annotation {ann!r}, want 'bool'"
        assert default is False, f"{name} must default OFF (was {default!r})"


def test_dividend_lane_switch_is_declared_optional_and_dark():
    f = _declared_fields()
    assert "trezo_dividend_lt_tcs" in f, "config.py does not declare trezo_dividend_lt_tcs"
    ann, default = f["trezo_dividend_lt_tcs"]
    assert ann == "int | None", ann
    assert default is None, (
        "trezo_dividend_lt_tcs must default None (unset -> _lane_tcs reads 0 -> dark)")


def test_every_reevaluator_tunable_is_declared_optional():
    """The code default now lives in ONE place -- reevaluator._TUNABLES and
    the two inline reads -- and Settings says only 'set' or 'not set'."""
    f = _declared_fields()
    for key, (attr, env, _default) in reeval._TUNABLES.items():
        assert attr in f, f"config.py does not declare {attr} ({key}/{env})"
        ann, default = f[attr]
        assert ann == "float | None", f"{attr}: {ann!r}"
        assert default is None, f"{attr}: default {default!r}, want None"
    for attr, code_default in REEVAL_INLINE.items():
        assert attr in f, f"config.py does not declare {attr}"
        ann, default = f[attr]
        want = "bool | None" if isinstance(code_default, bool) else "float | None"
        assert ann == want, f"{attr}: {ann!r}, want {want!r}"
        assert default is None, f"{attr}: default {default!r}, want None"


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
    missing = sorted(w for w in ALL_NEW_KNOBS if w not in fields)
    assert not missing, f"Settings.model_fields lacks {missing}"
    for name in sorted(OPTIONAL_KNOBS):
        assert fields[name].default is None, (name, fields[name].default)
    for name in LANE_SWITCHES:
        assert fields[name].default is False, (name, fields[name].default)
    # vf:config-web: the setting that makes a blank `KEY=` mean "unset".
    assert Settings.model_config.get("env_ignore_empty") is True, (
        "Settings must set env_ignore_empty=True or a blank typed value kills the boot")
    assert Settings.model_config.get("extra") == "ignore"


# --- the real reader code paths honour None and a declared value ------------

def test_reevaluator_tunable_reads_the_declared_settings_attr():
    for env in ("TREZO_REEVAL_COOLDOWN_SEC", "TREZO_REEVAL_STALE_DAYS"):
        assert os.getenv(env) is None, f"{env} set in this shell; test env is dirty"
    cfg = sys.modules["app.config"]
    d = _declared_defaults()
    # The declared defaults (all None for these knobs) on the settings
    # object -> every reader falls through to its exact code default.
    _assert_readers_answer_code_defaults(types.SimpleNamespace(**d))
    # An agents/.env override (a value on Settings) is honoured -- the
    # whole point of declaring the field.
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
    # Declared defaults (None) -> every lane OFF; None falls through to
    # the process env, which is clean here, then False.
    with _patched(scanner, get_settings=lambda: types.SimpleNamespace(**d)):
        for env in ("TREZO_DAY_OPTIONS", "TREZO_SPREADS", "TREZO_LONG_OPTIONS"):
            assert scanner._lane_enabled(env) is False
    # Flip ONE in "agents/.env" (i.e. on Settings) -> that lane only.
    with _patched(scanner, get_settings=lambda: types.SimpleNamespace(**dict(d, trezo_spreads=True))):
        assert scanner._lane_enabled("TREZO_SPREADS") is True
        assert scanner._lane_enabled("TREZO_DAY_OPTIONS") is False
        assert scanner._lane_enabled("TREZO_LONG_OPTIONS") is False
    assert scanner._lane_enabled("TREZO_SPREADS") is False


# --- boot safety: the template can be copied (vf:config-web) -----------------

def test_template_copied_verbatim_constructs_settings():
    """The finding, driven straight: Settings() from .env.example as the
    ONLY source. Before the fix this raised ValidationError on the first
    typed knob (float got '' or '# seconds', bool got '')."""
    S = _file_only_settings_class()
    s = S(_env_file=str(ENV_EXAMPLE))
    assert s.trading_mode == "paper"
    for name in sorted(OPTIONAL_KNOBS):
        assert getattr(s, name) is None, (name, getattr(s, name))
    for name in LANE_SWITCHES:
        assert getattr(s, name) is False, (name, getattr(s, name))
    # And the readers see that object as "everything at code default".
    _assert_readers_answer_code_defaults(s)


def test_every_template_key_blank_still_constructs_settings():
    """Every KEY the template names (set or commented out), written with a
    BLANK value, must construct the real Settings: blank means "unset ->
    code default" for typed and untyped fields alike. A temp file is the
    only source (never agents/.env, never the shell)."""
    keys = _template_keys()
    for k in ("PORT", "TREZO_DIVIDEND_LT_TCS", "TREZO_DAY_OPTIONS",
              "TREZO_REEVAL_STALE_DAYS", "MAX_POSITION_PCT"):
        assert k in keys, f"template key scan lost {k}"
    tmpdir = tempfile.mkdtemp(prefix="trezo_env_guard_")
    path = Path(tmpdir) / "all_blank.env"
    try:
        path.write_text("".join(f"{k}=\n" for k in keys), encoding="utf-8")
        S = _file_only_settings_class()
        s = S(_env_file=str(path))
    finally:
        try:
            path.unlink()
            os.rmdir(tmpdir)
        except OSError:
            pass
    # Typed fields keep their code defaults instead of failing to parse "".
    assert s.port == 8001 and s.max_position_pct == 0.25
    assert s.trezo_crypto_tcs_floor == 35
    assert s.trading_mode == "paper" and s.trezo_accounts_enabled == "primary"
    for name in sorted(OPTIONAL_KNOBS):
        assert getattr(s, name) is None, (name, getattr(s, name))
    for name in LANE_SWITCHES:
        assert getattr(s, name) is False, (name, getattr(s, name))
    _assert_readers_answer_code_defaults(s)


def test_a_set_knob_still_binds_through_the_real_settings_class():
    """Boot-safety must not have cost the binding: a value written for a
    knob reaches the reader, typed."""
    tmpdir = tempfile.mkdtemp(prefix="trezo_env_guard_")
    path = Path(tmpdir) / "set.env"
    try:
        path.write_text("TREZO_REEVAL_STALE_DAYS=2.5\nTREZO_SPREADS=true\n"
                        "TREZO_DIVIDEND_LT_TCS=75\nTREZO_REEVAL_TCS_RESCORE=false\n",
                        encoding="utf-8")
        S = _file_only_settings_class()
        s = S(_env_file=str(path))
    finally:
        try:
            path.unlink()
            os.rmdir(tmpdir)
        except OSError:
            pass
    assert s.trezo_reeval_stale_days == 2.5 and s.trezo_dividend_lt_tcs == 75
    assert s.trezo_spreads is True and s.trezo_reeval_tcs_rescore is False
    assert s.trezo_day_options is False and s.trezo_reeval_cooldown_sec is None
    cfg = sys.modules["app.config"]
    with _patched(cfg, get_settings=lambda: s):
        assert reeval.tunable("STALE_DAYS") == 2.5
        assert reeval.tunable("COOLDOWN_SEC") == 900.0
        assert reeval._settings_flag("trezo_reeval_tcs_rescore",
                                     "TREZO_REEVAL_TCS_RESCORE", True) is False
    with _patched(scanner, get_settings=lambda: s):
        assert scanner._lane_enabled("TREZO_SPREADS") is True
        assert scanner._lane_enabled("TREZO_DAY_OPTIONS") is False


# --- operator surface --------------------------------------------------------

def test_env_example_documents_every_new_key_commented_out_with_its_default():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    want = {
        "TREZO_DIVIDEND_LT_TCS": "0",
        "TREZO_DAY_OPTIONS": "false", "TREZO_SPREADS": "false",
        "TREZO_LONG_OPTIONS": "false",
        "TREZO_REEVAL_TCS_COLLAPSE_FRAC": "0.5",
        "TREZO_REEVAL_SHADOW_FAR_PCT": "0.03",
        "TREZO_REEVAL_TCS_RESCORE": "true",
    }
    for _key, (attr, env, default) in reeval._TUNABLES.items():
        want[env] = default
    for env, default in want.items():
        m = re.search(rf"^(#?)\s*{env}=(.*)$", text, re.M)
        assert m, f".env.example lacks {env}"
        assert m.group(1) == "#", f"{env} must be COMMENTED OUT in the template (vf:config-web)"
        shown = m.group(2).strip()
        assert shown and "#" not in shown, f"{env}: '{shown}' -- value on the line, notes on their own"
        assert float(shown) == float(default) if shown not in ("true", "false") \
            else shown == str(default).lower(), (env, shown, default)
    assert "TREZO_DIVIDEND_LT_TCS" in text and "ON-SWITCH" in text.upper()
    assert "blank = dark" not in text.lower() and "blank = the lane" not in text.lower()
    assert "tcs_threshold" in text, "the dividend switch must say it has to exceed the book's tcs_threshold"


def test_env_example_swallows_no_comment_as_a_value():
    """dotenv reads `KEY=   # note` as the value '# note' (the whitespace
    after '=' is consumed first, so the inline-comment strip never fires).
    Four macro API keys and two tooling keys shipped that way -- a str
    field silently 'set' to its own comment -- and the typed knobs failed
    to parse it. No template value may start with '#'."""
    from dotenv import dotenv_values
    vals = dotenv_values(str(ENV_EXAMPLE))
    swallowed = sorted(k for k, v in vals.items() if v and v.lstrip().startswith("#"))
    assert not swallowed, f".env.example values that are really comments: {swallowed}"


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
