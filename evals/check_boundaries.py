"""CI dependency direction and minimal-install checks."""
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ('PyQt6', 'qfluentwidgets', 'pytestqt', 'uiautomation', 'keyring', 'litellm', 'openai', 'anthropic'):
    assert importlib.util.find_spec(name) is None, f'Desktop dependency installed: {name}'
for folder, forbidden in ((ROOT / 'app', 'nemo_eval'), (ROOT / 'evals/src/nemo_eval', 'app')):
    for path in folder.rglob('*.py'):
        if folder.name == 'nemo_eval' and 'adapters' in path.relative_to(folder).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            elif isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            else:
                continue
            assert all(n != forbidden and not n.startswith(forbidden + '.') for n in names), path
print('Independent package dependency boundaries passed')
