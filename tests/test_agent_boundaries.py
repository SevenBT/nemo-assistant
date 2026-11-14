"""Protect the core dependency boundary in source and in a fresh interpreter."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def test_core_only_imports_standard_library_and_neutral_runtime():
    for folder in ("app/agent", "app/runtime"):
        for path in (ROOT / folder).rglob("*.py"):
            package = ".".join(path.relative_to(ROOT).with_suffix("").parts[:-1])
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    name = node.module or ""
                    if node.level:
                        name = importlib.util.resolve_name("." * node.level + name, package)
                    names = [name]
                elif isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                else:
                    continue
                for name in names:
                    assert (
                        name.split(".")[0] in sys.stdlib_module_names
                        or name == "app.agent" or name.startswith("app.agent.")
                        or name == "app.runtime" or name.startswith("app.runtime.")
                    ), (path, node.lineno, name)


def test_core_runs_without_application_services_or_personal_data():
    script = textwrap.dedent('''
        import builtins, importlib, json, os, pathlib, sys
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.startswith('app.') and not name.startswith(('app.agent', 'app.runtime')):
                raise AssertionError('Application service imported: ' + name)
            if name.split('.')[0] in ('PyQt6', 'qfluentwidgets', 'keyring', 'sqlite3'):
                raise AssertionError('Desktop dependency imported: ' + name)
            return original_import(name, *args, **kwargs)
        builtins.__import__ = guarded_import
        protected = [pathlib.Path.cwd() / name for name in ('config', 'data', 'logs')]
        def audit(event, args):
            if event == 'open' and isinstance(args[0], (str, bytes)):
                path = pathlib.Path(os.fsdecode(args[0])).resolve()
                assert not any(path.is_relative_to(root) for root in protected), path
        sys.addaudithook(audit)
        for path in pathlib.Path('app/agent').glob('*.py'):
            importlib.import_module('app.agent.' + path.stem)
        from app.agent.agent import Agent
        from app.agent.agent_context import AgentContext
        from app.agent.contracts import ToolDescriptor
        from app.agent.agent_interface import AgentCallbacks
        class Model:
            def __init__(self):
                self.calls = 0
            def chat_stream(self, messages, tools, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    for index in range(2):
                        yield dict(type='tool_call', id=str(index), name='write', arguments={})
                else:
                    assert [m['tool_call_id'] for m in messages if m['role'] == 'tool'] == ['0', '1']
                    assistant = next(m for m in messages if m['role'] == 'assistant')
                    assert all(json.loads(c['function']['arguments']) == {} for c in assistant['tool_calls'])
                    yield dict(type='text', delta='ok')
                yield dict(type='done')
        class Tools:
            def definitions(self):
                return []
            def describe(self, name):
                return ToolDescriptor(name)
            def execute(self, name, arguments, context):
                assert context.session_id == 'isolated'
                assert arguments == {}
                arguments['mutation'] = True
                return dict(status='success', data={})
            def format_result(self, result):
                return json.dumps(result)
        def mutate_progress(call_id, name, params):
            params['callback_mutation'] = True
        def mutate_result(call_id, name, result):
            result['status'] = 'error'
        callbacks = AgentCallbacks(on_tool_start=mutate_progress, on_tool_done=mutate_result)
        result = Agent(AgentContext(llm_gateway=Model(), registry=Tools(), callbacks=callbacks),
                       [dict(role='user', content='run')], session_id='isolated').run_sync()
        assert result['ok'], result
        assert not any(n.startswith(('app.config', 'app.storage', 'app.llm', 'app.tools', 'app.adapters'))
                       for n in sys.modules)
    ''')
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
