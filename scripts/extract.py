#!/usr/bin/env python3
"""extract.py — top-level orchestrator for converting a .make file into a clean local project.

Runs the full pipeline:
  1. unzip the .make archive into a working directory
  2. decode canvas.fig (via Node) into decoded-message.json
  3. reconstruct the source tree at codeFilePath/name from CODE_FILE nodes
  4. scaffold (package.json, vite config, tsconfig, index.html, main.tsx)
  5. generate docs (README, CLAUDE.md, design brief, chat archive)
  6. (optional) npm install + npm run build to verify

Usage:
    extract.py <input.make> <output-dir> [--name PROJECT_NAME] [--no-build]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def slugify(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != '-':
            out.append('-')
    return ''.join(out).strip('-') or 'figma-make-project'


def run(cmd, cwd=None, check=True):
    print(f'\n$ {" ".join(str(c) for c in cmd)}')
    result = subprocess.run(cmd, cwd=cwd, check=False)
    if check and result.returncode != 0:
        print(f'command failed with exit code {result.returncode}', file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def ensure_node_deps():
    """Install kiwi-schema/pako/fzstd into scripts/ if not already present."""
    if (SCRIPT_DIR / 'node_modules' / 'kiwi-schema').exists():
        return
    print('Installing Node decoder dependencies (one-time setup)...')
    run(['npm', 'install', '--silent'], cwd=SCRIPT_DIR)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('input', type=Path, help='path to the .make file')
    ap.add_argument('output', type=Path, help='directory to create the project in')
    ap.add_argument('--name', help='project name (defaults to slug of .make filename)')
    ap.add_argument('--no-build', action='store_true', help='skip npm install + build verification')
    ap.add_argument('--force', action='store_true', help='allow overwriting an existing non-project directory (dangerous!)')
    args = ap.parse_args()

    if not args.input.exists():
        print(f'error: input file not found: {args.input}', file=sys.stderr)
        sys.exit(1)

    name = args.name or slugify(args.input.stem)

    # Use a temp working directory to keep the user's filesystem clean.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        extracted = tmp / 'extracted'
        extracted.mkdir()

        # 1. Unzip
        print(f'Unpacking {args.input} ...')
        try:
            with zipfile.ZipFile(args.input) as z:
                z.extractall(extracted)
        except zipfile.BadZipFile:
            print(
                f'error: {args.input} is not a valid ZIP archive. '
                f'Figma Make `.make` files are ZIP archives — please confirm this '
                f"file isn't truncated or wasn't accidentally renamed from another format.",
                file=sys.stderr,
            )
            sys.exit(2)
        canvas_fig = extracted / 'canvas.fig'
        if not canvas_fig.exists():
            print(f'error: archive does not contain canvas.fig — is this really a .make file?', file=sys.stderr)
            sys.exit(2)

        # 2. Decode canvas
        ensure_node_deps()
        decoded_json = tmp / 'decoded.json'
        run(['node', str(SCRIPT_DIR / 'decode_canvas.js'), str(canvas_fig), str(decoded_json)])

        # 3. Reconstruct
        reconstruct_cmd = [
            'python3', str(SCRIPT_DIR / 'reconstruct.py'),
            '--decoded', str(decoded_json),
            '--extracted', str(extracted),
            '--out', str(args.output),
        ]
        if args.force:
            reconstruct_cmd.append('--force')
        run(reconstruct_cmd)

        # 4. Scaffold
        run([
            'python3', str(SCRIPT_DIR / 'scaffold.py'),
            '--project', str(args.output),
            '--name', name,
        ])

        # 5. Docs
        run([
            'python3', str(SCRIPT_DIR / 'make_docs.py'),
            '--project', str(args.output),
            '--extracted', str(extracted),
            '--name', name,
        ])

    # 6. Verify build (unless skipped)
    if args.no_build:
        print('\nSkipping npm install + build verification (per --no-build).')
    else:
        print('\nVerifying with npm install + npm run build ...')
        # --legacy-peer-deps so users with strict-peer-dep npm versions don't choke
        # on the typical Radix peer-dep storm.
        rc = run(['npm', 'install', '--legacy-peer-deps'], cwd=args.output, check=False)
        if rc != 0:
            print(
                '\nnpm install failed. The source tree was still extracted to '
                f'{args.output}; you can investigate and run install yourself.',
                file=sys.stderr,
            )
            sys.exit(rc)
        rc = run(['npm', 'run', 'build'], cwd=args.output, check=False)
        if rc != 0:
            print(
                '\nBuild failed. The source tree is at '
                f'{args.output}. Common causes: a dep needs a different version '
                "than the skill's KNOWN_VERSIONS table assumes, or a CSS file "
                'imports a package not yet detected. Inspect the error and '
                'adjust package.json.',
                file=sys.stderr,
            )
            sys.exit(rc)
        print('\n✓ Build succeeded.')

    print(f'\nDone. Project at: {args.output}')
    print(f'Run it with:  cd {args.output} && npm run dev')


if __name__ == '__main__':
    main()
