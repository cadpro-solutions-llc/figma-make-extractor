#!/usr/bin/env python3
"""reconstruct.py — turn a decoded canvas message into a project file tree.

Walks all CODE_FILE nodes, writes their sourceCode to disk at codeFilePath/name,
applies safe rewrites (strip pinned-version specifiers from imports, convert
figma:asset imports to public/ asset references), and copies referenced assets
out of the make archive's `images/` and `make_binary_files/` blob folders.

The Figma Make convention is to put source under `src/app/...`. Most local
React/Vite projects just use `src/...`, so we collapse `src/app` -> `src`.
This is a content-preserving rename — relative imports inside the tree still
work because every file is moved by the same prefix.

Usage:
    reconstruct.py --decoded <decoded.json> --extracted <make-extract-dir> --out <project-dir>
"""
import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

# Files Figma includes inside the canvas tree that we'll regenerate from scratch
# during scaffolding. Keeping the originals would conflict with our generated versions.
SCAFFOLD_OWNED = {
    'package.json',
    'vite.config.ts',
    'vite.config.js',
    'tsconfig.json',
    'tsconfig.node.json',
    'index.html',
    'src/main.tsx',
    'src/main.ts',
    # Figma-specific package-manager files we don't want to inherit
    'pnpm-lock.yaml',
    'pnpm-workspace.yaml',
    '.npmrc',
    'package-lock.json',
    'yarn.lock',
}

# Strip pinned version specifiers from imports.
#   from "@radix-ui/react-foo@1.2.3"        -> from "@radix-ui/react-foo"
#   from "@radix-ui/react-foo@1.2.3/sub"    -> from "@radix-ui/react-foo/sub"
# We deliberately match only "@x.y" or "@x.y.z" right after the package name to
# avoid touching legitimate uses of '@' inside paths.
PINNED_VERSION_RE = re.compile(r'''(from\s+["'])([^"'\s]+?)@\d+\.\d+(?:\.\d+)?([^"']*)(["'])''')

# `import logo from 'figma:asset/HASH.png'`  -> `const logo = "/assets/HASH.png";`
# Figma stores asset blobs in images/ and make_binary_files/ keyed by hash, no extension.
FIGMA_ASSET_IMPORT_RE = re.compile(
    r'''import\s+(\w+)\s+from\s+["']figma:asset/([^"'?]+)(?:\?[^"']*)?["'];?'''
)


def walk_code_files(obj):
    """Yield every node with type == 'CODE_FILE', wherever it sits in the tree."""
    if isinstance(obj, dict):
        if obj.get('type') == 'CODE_FILE':
            yield obj
        for v in obj.values():
            yield from walk_code_files(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_code_files(item)


def normalize_path(code_file_path: str, name: str) -> str:
    full = f"{code_file_path or ''}/{name}".strip('/')
    if full == 'src/app':
        return 'src'
    if full.startswith('src/app/'):
        return 'src/' + full[len('src/app/'):]
    return full


def fix_imports(content: str) -> str:
    return PINNED_VERSION_RE.sub(r'\1\2\3\4', content)


def convert_figma_asset_imports(content: str):
    """Rewrite figma:asset imports to public/assets URL constants.

    Returns (new_content, set_of_(hash, ext)_tuples_referenced).
    """
    referenced = set()

    def repl(m):
        var = m.group(1)
        asset_ref = m.group(2)
        # asset_ref examples: "abc123.png", "abc123" (no ext), "abc123.svg"
        if '.' in asset_ref:
            hash_part, ext = asset_ref.rsplit('.', 1)
        else:
            hash_part, ext = asset_ref, 'png'
        referenced.add((hash_part, ext))
        return f'const {var} = "/assets/{hash_part}.{ext}";'

    return FIGMA_ASSET_IMPORT_RE.sub(repl, content), referenced


def copy_assets(referenced, extracted_dir: Path, out_dir: Path):
    """Copy referenced asset blobs into out/public/assets/ with proper extensions."""
    if not referenced:
        return 0
    assets_dir = out_dir / 'public' / 'assets'
    assets_dir.mkdir(parents=True, exist_ok=True)
    blob_sources = [extracted_dir / 'images', extracted_dir / 'make_binary_files']
    copied = 0
    missing = []
    for hash_part, ext in referenced:
        for src_dir in blob_sources:
            candidate = src_dir / hash_part
            if candidate.exists():
                shutil.copy(candidate, assets_dir / f'{hash_part}.{ext}')
                copied += 1
                break
        else:
            missing.append(f'{hash_part}.{ext}')
    if missing:
        print(f'warning: {len(missing)} referenced assets not found in archive blob folders:', file=sys.stderr)
        for m in missing[:5]:
            print(f'  - {m}', file=sys.stderr)
    return copied


def safe_rmtree(path: Path, force: bool = False) -> None:
    """Remove a directory tree safely.

    1. Refuses to delete protected paths (home dir, system dirs, CWD).
    2. Warns and lists contents before deleting non-project directories
       unless ``force`` is True.
    3. Retries after chmod on read-only files (Windows).
    """
    resolved = path.resolve()

    # --- Protected path checks (never allowed, even with --force) ---
    home = Path.home().resolve()
    if resolved == home or str(resolved).startswith(str(home) + os.sep):
        print(f'error: refusing to delete home directory or its contents: {path}', file=sys.stderr)
        sys.exit(1)

    cwd = Path.cwd().resolve()
    if resolved == cwd:
        print(f'error: refusing to delete current working directory: {path}', file=sys.stderr)
        sys.exit(1)

    # System directories (Windows)
    system_roots = [
        Path(os.environ.get('SystemRoot', r'C:\Windows')).resolve(),
        Path(r'C:\Program Files').resolve(),
        Path(r'C:\Program Files (x86)').resolve(),
        Path(r'C:\ProgramData').resolve(),
    ]
    for sys_root in system_roots:
        if resolved == sys_root or str(resolved).startswith(str(sys_root) + os.sep):
            print(f'error: refusing to delete system directory: {path}', file=sys.stderr)
            sys.exit(1)

    # Unix root
    if resolved == Path('/').resolve():
        print('error: refusing to delete root directory', file=sys.stderr)
        sys.exit(1)

    # --- Project-directory heuristic (skip if force) ---
    if not force and path.is_dir():
        looks_like_project = any((path / marker).exists() for marker in ('package.json', 'src', 'vite.config.ts', 'tsconfig.json'))
        if not looks_like_project:
            item_count = sum(1 for _ in path.rglob('*'))
            print(f'warning: {path} does not look like a project directory ({item_count} items)', file=sys.stderr)
            print(f'  Pass --force to overwrite anyway.', file=sys.stderr)
            sys.exit(1)

    # --- Log and delete ---
    if path.is_dir():
        item_count = sum(1 for _ in path.rglob('*'))
        print(f'Removing existing directory: {path} ({item_count} items)...')
    else:
        print(f'Removing existing file: {path}...')

    def onerror(func, filepath, exc_info):
        if not os.access(filepath, os.W_OK):
            os.chmod(filepath, stat.S_IWUSR)
            func(filepath)
        else:
            raise
    shutil.rmtree(path, onerror=onerror)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--decoded', required=True, type=Path)
    ap.add_argument('--extracted', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--force', action='store_true', help='allow overwriting non-project directories')
    args = ap.parse_args()

    if args.out.exists():
        safe_rmtree(args.out, force=args.force)
    args.out.mkdir(parents=True)

    with args.decoded.open() as f:
        data = json.load(f)

    written = 0
    skipped_owned = 0
    referenced_assets = set()
    seen = set()

    for node in walk_code_files(data):
        name = node.get('name') or ''
        if not name:
            continue
        rel = normalize_path(node.get('codeFilePath') or '', name)
        if rel in seen:
            continue
        seen.add(rel)

        if rel in SCAFFOLD_OWNED:
            skipped_owned += 1
            continue

        src = node.get('sourceCode') or ''

        if rel.endswith(('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')):
            src = fix_imports(src)
            src, refs = convert_figma_asset_imports(src)
            referenced_assets |= refs

        target = args.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src)
        written += 1

    copied = copy_assets(referenced_assets, args.extracted, args.out)

    print(f'Wrote {written} files; skipped {skipped_owned} scaffolding-owned files; '
          f'copied {copied}/{len(referenced_assets)} referenced assets')


if __name__ == '__main__':
    main()
