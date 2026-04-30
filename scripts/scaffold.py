#!/usr/bin/env python3
"""scaffold.py — add a Vite + React scaffolding around a reconstructed src tree.

Generates package.json (with deps detected from imports), vite.config.ts,
tsconfig.json, tsconfig.node.json, index.html, and src/main.tsx.

We auto-detect deps from real imports rather than reusing Figma's starter
package.json, because Figma's starter pins ~50 packages most of which the
final project never uses. The user can review the trimmed list and
restore anything they want.

Usage: scaffold.py --project <project-dir> --name <project-name>
"""
import argparse
import json
import re
import sys
from pathlib import Path

# from "..." or from '...' — captures the specifier
JS_IMPORT_RE = re.compile(r'''from\s+["']([^"']+)["']''')
# CSS @import 'pkg' (only the bare-specifier form; relative imports start with . or url())
CSS_IMPORT_RE = re.compile(r'''@import\s+["']([^./"'][^"']*)["']''')

# Bare specifiers that resolve to subpaths of packages already covered, so we
# shouldn't add them as separate dependencies.
SKIP_SPECIFIERS = {
    'react/jsx-runtime',
    'react-dom/client',
    'react-dom/server',
}

# Reasonably current versions for packages commonly seen in Figma Make exports.
# Anything not listed here gets 'latest' (npm will resolve at install time).
KNOWN_VERSIONS = {
    'react': '^18.3.1',
    'react-dom': '^18.3.1',
    '@types/react': '^18.3.0',
    '@types/react-dom': '^18.3.0',
    '@types/node': '^20.11.0',
    '@vitejs/plugin-react': '^4.3.0',
    '@tailwindcss/vite': '^4.1.0',
    'tailwindcss': '^4.1.0',
    'tw-animate-css': '^1.0.0',
    'typescript': '^5.4.0',
    'vite': '^5.4.0',
    'lucide-react': '^0.460.0',
    'class-variance-authority': '^0.7.0',
    'clsx': '^2.1.0',
    'tailwind-merge': '^2.5.0',
    'motion': '^11.11.0',
    'sonner': '^1.5.0',
    'cmdk': '^1.0.0',
    'date-fns': '^3.6.0',
    'recharts': '^2.13.0',
    'react-hook-form': '^7.53.0',
    'zod': '^3.23.0',
    '@hookform/resolvers': '^3.9.0',
    'embla-carousel-react': '^8.3.0',
    'input-otp': '^1.2.4',
    'next-themes': '^0.4.0',
    'react-day-picker': '^8.10.1',
    'react-resizable-panels': '^2.1.0',
    'vaul': '^1.0.0',
    'canvas-confetti': '^1.9.3',
    'react-router-dom': '^6.27.0',
    'react-router': '^6.27.0',
    'react-dnd': '^16.0.1',
    'react-dnd-html5-backend': '^16.0.1',
}


def root_package_name(spec: str) -> str:
    """'@scope/pkg/sub' -> '@scope/pkg', 'pkg/sub' -> 'pkg'."""
    if spec.startswith('@'):
        parts = spec.split('/', 2)
        return '/'.join(parts[:2])
    return spec.split('/', 1)[0]


def collect_imports(src_dir: Path) -> set[str]:
    pkgs: set[str] = set()
    for ext in ('*.ts', '*.tsx', '*.js', '*.jsx', '*.mjs', '*.cjs'):
        for f in src_dir.rglob(ext):
            try:
                text = f.read_text()
            except Exception:
                continue
            for m in JS_IMPORT_RE.finditer(text):
                spec = m.group(1)
                if (
                    spec.startswith('.')
                    or spec.startswith('/')
                    or spec.startswith('@/')
                    or spec.startswith('figma:')
                    or spec in SKIP_SPECIFIERS
                ):
                    continue
                pkgs.add(root_package_name(spec))
    # CSS files can also pull in npm packages (e.g. tw-animate-css)
    for css in src_dir.rglob('*.css'):
        try:
            text = css.read_text()
        except Exception:
            continue
        for m in CSS_IMPORT_RE.finditer(text):
            spec = m.group(1).split(' ')[0].strip()  # strip Tailwind v4 'source(...)' modifiers
            if not spec or spec.startswith(('http://', 'https://')):
                continue
            pkgs.add(root_package_name(spec))
    return pkgs


def find_css_entry(src_dir: Path) -> str | None:
    """Find the top-level CSS the app should import in main.tsx.

    Prefers files most likely to be the orchestrating entry. Skips empty files.
    """
    candidates = [
        'styles/index.css',
        'styles/globals.css',
        'styles/main.css',
        'index.css',
        'globals.css',
    ]
    for c in candidates:
        p = src_dir / c
        if p.exists() and p.stat().st_size > 0:
            return f'./{c}'
    # Fallback: any non-empty .css in src/
    for css in src_dir.rglob('*.css'):
        if css.stat().st_size > 0:
            return './' + str(css.relative_to(src_dir))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True, type=Path)
    ap.add_argument('--name', required=True)
    args = ap.parse_args()

    src = args.project / 'src'
    if not src.exists():
        print('error: no src/ directory found in project — nothing to scaffold around', file=sys.stderr)
        sys.exit(1)

    pkgs = collect_imports(src)
    pkgs.update({'react', 'react-dom'})  # always required even if unscanned

    # Heuristic: if any tailwind v4 directives appear in CSS, ensure tailwindcss + plugin
    has_tailwind_v4 = False
    for css in src.rglob('*.css'):
        try:
            text = css.read_text()
        except Exception:
            continue
        if '@tailwind' in text or "@import 'tailwindcss'" in text or '@import "tailwindcss"' in text or '@theme' in text or '@custom-variant' in text:
            has_tailwind_v4 = True
            break

    deps = {p: KNOWN_VERSIONS.get(p, 'latest') for p in pkgs}
    deps = dict(sorted(deps.items()))

    dev_deps = {
        '@types/react': KNOWN_VERSIONS['@types/react'],
        '@types/react-dom': KNOWN_VERSIONS['@types/react-dom'],
        '@types/node': KNOWN_VERSIONS['@types/node'],
        '@vitejs/plugin-react': KNOWN_VERSIONS['@vitejs/plugin-react'],
        'typescript': KNOWN_VERSIONS['typescript'],
        'vite': KNOWN_VERSIONS['vite'],
    }
    if has_tailwind_v4:
        dev_deps['@tailwindcss/vite'] = KNOWN_VERSIONS['@tailwindcss/vite']
        dev_deps['tailwindcss'] = KNOWN_VERSIONS['tailwindcss']
    dev_deps = dict(sorted(dev_deps.items()))

    pkg_json = {
        'name': args.name,
        'private': True,
        'version': '0.0.1',
        'type': 'module',
        'scripts': {
            'dev': 'vite',
            'build': 'vite build',
            'preview': 'vite preview',
        },
        'dependencies': deps,
        'devDependencies': dev_deps,
    }
    (args.project / 'package.json').write_text(json.dumps(pkg_json, indent=2) + '\n')

    plugin_imports = ["import react from '@vitejs/plugin-react';"]
    plugin_calls = ['react()']
    if has_tailwind_v4:
        plugin_imports.append("import tailwindcss from '@tailwindcss/vite';")
        plugin_calls.append('tailwindcss()')

    vite_config = (
        "import { defineConfig } from 'vite';\n"
        + '\n'.join(plugin_imports)
        + "\nimport path from 'path';\n\n"
        + 'export default defineConfig({\n'
        + f'  plugins: [{", ".join(plugin_calls)}],\n'
        + '  resolve: {\n'
        + "    alias: {\n      '@': path.resolve(__dirname, './src'),\n    },\n"
        + '  },\n'
        + '});\n'
    )
    (args.project / 'vite.config.ts').write_text(vite_config)

    tsconfig = {
        'compilerOptions': {
            'target': 'ES2020',
            'useDefineForClassFields': True,
            'lib': ['ES2020', 'DOM', 'DOM.Iterable'],
            'module': 'ESNext',
            'skipLibCheck': True,
            'moduleResolution': 'bundler',
            'allowImportingTsExtensions': True,
            'resolveJsonModule': True,
            'isolatedModules': True,
            'noEmit': True,
            'jsx': 'react-jsx',
            'strict': False,
            'noUnusedLocals': False,
            'noUnusedParameters': False,
            'noFallthroughCasesInSwitch': True,
            'baseUrl': '.',
            'paths': {'@/*': ['src/*']},
        },
        'include': ['src'],
        'references': [{'path': './tsconfig.node.json'}],
    }
    (args.project / 'tsconfig.json').write_text(json.dumps(tsconfig, indent=2) + '\n')

    tsconfig_node = {
        'compilerOptions': {
            'composite': True,
            'skipLibCheck': True,
            'module': 'ESNext',
            'moduleResolution': 'bundler',
            'allowSyntheticDefaultImports': True,
            'strict': True,
        },
        'include': ['vite.config.ts'],
    }
    (args.project / 'tsconfig.node.json').write_text(json.dumps(tsconfig_node, indent=2) + '\n')

    (args.project / 'index.html').write_text(
        f'<!doctype html>\n'
        f'<html lang="en">\n'
        f'  <head>\n'
        f'    <meta charset="UTF-8" />\n'
        f'    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f'    <title>{args.name}</title>\n'
        f'  </head>\n'
        f'  <body>\n'
        f'    <div id="root"></div>\n'
        f'    <script type="module" src="/src/main.tsx"></script>\n'
        f'  </body>\n'
        f'</html>\n'
    )

    css_entry = find_css_entry(src)
    css_import_line = f"import '{css_entry}';\n" if css_entry else ''
    (src / 'main.tsx').write_text(
        "import { StrictMode } from 'react';\n"
        "import { createRoot } from 'react-dom/client';\n"
        "import App from './App';\n"
        f'{css_import_line}'
        '\n'
        "createRoot(document.getElementById('root')!).render(\n"
        '  <StrictMode>\n'
        '    <App />\n'
        '  </StrictMode>,\n'
        ');\n'
    )

    # Helpful .gitignore
    (args.project / '.gitignore').write_text(
        'node_modules/\ndist/\n.vite/\n.DS_Store\n*.log\n'
    )

    print(f'Detected {len(deps)} runtime deps; tailwind v4 detected: {has_tailwind_v4}')
    print(f'CSS entry: {css_entry or "(none — main.tsx will not import any global CSS)"}')


if __name__ == '__main__':
    main()
