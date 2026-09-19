"""Check tracked publication files and relative documentation links."""
from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = (
    '.local/*', '.belgu/*', '.venv/*', '.superpowers/*', '.codex/*',
    '.claude/*', '.agents/*', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md',
    'docs/superpowers/*', 'docs/social/*', 'docs/publishing.md',
    'docs/design/*', 'docs/implementation-notes.md', 'docs/live-workflow-check.md',
    'evals/results/*', 'web/qa/*', 'scripts/render_product_tour.py',
    '*.db', '*.db-*', '*.sqlite*', '*.gguf', '*.safetensors', '*.bundle',
    '*.log', '*.pem', '*.key', 'integrations.json', '.env', '.env.*',
    'node_modules/*', 'web/node_modules/*', 'web/dist/*',
)


def main() -> int:
    paths = subprocess.check_output(
        ['git', 'ls-files', '-z'], cwd=ROOT,
    ).decode().split('\0')
    tracked = {path for path in paths if path}
    errors: list[str] = []
    docs = 0
    for name in sorted(tracked):
        if name != '.env.example' and any(fnmatch.fnmatchcase(name, pattern) for pattern in EXCLUDED):
            errors.append(f'{name}: local or generated file is tracked')
        if not name.endswith('.md'):
            continue
        docs += 1
        path = ROOT / name
        body = path.read_text(encoding='utf-8')
        if re.search(r'/(?:home|Users)/[^\s/]+/', body):
            errors.append(f'{name}: machine-specific home path')
        for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', body):
            target = target.strip('<>')
            url = urlsplit(target)
            if url.scheme:
                if url.hostname in {'localhost', '127.0.0.1', '::1'}:
                    errors.append(f'{name}: loopback URL presented as a clickable link')
                continue
            if not url.path:
                continue
            resolved = (path.parent / unquote(url.path)).resolve()
            try:
                relative = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                errors.append(f'{name}: link leaves the repository: {target}')
                continue
            if relative not in tracked and not any(p.startswith(relative + '/') for p in tracked):
                errors.append(f'{name}: link does not resolve to tracked content: {target}')
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Publication checks passed: {len(tracked)} tracked files, {docs} Markdown documents.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
