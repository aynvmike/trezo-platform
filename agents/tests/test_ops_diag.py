"""Read-only host diagnostic must use the actual Supabase schema/beacon."""
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import run_tests, stub_config
stub_config()
spec = importlib.util.spec_from_file_location('_trezo_ops_diag_test', Path(__file__).resolve().parents[2]/'ops/diag.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def test_engine_diagnostic_reads_live_schema_and_deployed_boot_shape():
    seen = []
    uid = diag.BOOKS[0][1]
    at = '2026-09-30T18:00:00+00:00'
    class FakeSB:
        def get(self, table, query, limit=None):
            seen.append((table, query))
            if table == 'agent_messages':
                assert 'agent_name' in query and ',agent,' not in query
                return 200, [{'created_at': at, 'agent_name': 'trade_execution', 'kind': 'info'}], 0
            if table == 'paper_positions':
                assert ',quantity,' in query and ',qty,' not in query
                return 200, [], 0
            if table == 'ops_log_tail':
                return 200, [{'ts': at, 'host': 'test', 'line': {'event': 'engine_boot',
                    'reason': 'engine process started: pid=4548 commit=376fce1 agents=30'}}], 0
            if table == 'bot_settings': return 200, [{'user_id': uid}], 0
            return 200, [], 0
    old_out, old_verdict = diag.OUT, diag.VERDICT
    diag.OUT, diag.VERDICT = io.StringIO(), []
    try:
        with redirect_stdout(io.StringIO()): diag.section_engine(FakeSB(), at)
        output = diag.OUT.getvalue()
        assert 'commit=376fce1' in output and "'pid': '4548'" in output
        assert 'trade_execution' in output and 'bus: newest msg' in ' '.join(diag.VERDICT)
        assert len([s for s in seen if s[0] == 'paper_positions']) == 2
    finally:
        diag.OUT, diag.VERDICT = old_out, old_verdict


def test_structured_boot_fields_take_precedence_and_missing_stays_unknown():
    assert diag.boot_details({'commit': 'new', 'reason': 'commit=old pid=7 agents=30'}) == {'commit': 'new', 'pid': '7', 'agents': '30'}
    assert diag.boot_details({})['commit'] == '?'


if __name__ == '__main__': raise SystemExit(run_tests(globals()))
