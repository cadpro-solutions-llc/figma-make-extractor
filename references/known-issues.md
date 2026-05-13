# Known Issues and Caveats

Last reviewed: 2026-05-12

## Medium Severity

### 1. Missing error handling in decoder (`scripts/decode_canvas.js`)
- **Lines**: 45 (`pako.inflateRaw`), 52 (`fzstd.decompress`)
- **Issue**: No try/catch around decompression calls. Corrupted `.make` files produce unhelpful raw stack traces instead of clean error messages.
- **Impact**: User sees Node internal errors rather than "corrupted archive" or "invalid canvas.fig"
- **Mitigation**: Only use with trusted Figma Make exports. If decoding fails, look for "incorrect header check" or zstd-related errors in the stack trace.

## Low Severity

### 2. `__dirname` used in ESM context (`scripts/scaffold.py`)
- **Line**: 206
- **Issue**: Generated `vite.config.ts` uses `__dirname` which is `undefined` in pure ESM (`"type": "module"`).
- **Impact**: Vite currently polyfills `__dirname` in config files, so builds succeed today. Future Vite versions may remove this polyfill.
- **Mitigation**: If builds fail with `__dirname is not defined`, patch the generated config:
  ```ts
  import { fileURLToPath } from 'url';
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  ```

### 3. Path traversal possible (`scripts/reconstruct.py`)
- **Line**: 71 (`normalize_path`)
- **Issue**: Does not sanitize `..` sequences in `codeFilePath`. A malicious `.make` could write outside the output directory.
- **Impact**: Low — `.make` files are user-generated exports from Figma Make, not untrusted input.
- **Mitigation**: Only process exports from trusted Figma Make sessions.

### 4. CSS `@import url()` not detected (`scripts/scaffold.py`)
- **Line**: 23 (`CSS_IMPORT_RE`)
- **Issue**: Regex only matches `@import "pkg"` / `@import 'pkg'`. Misses `@import url('pkg')`.
- **Impact**: Rare — Tailwind v4 projects typically use quoted imports. If a package is missing after extraction, check CSS files for `url()` syntax.
- **Mitigation**: Manually add missing packages to `package.json` if detected.

### 5. Potential KeyError (`scripts/make_docs.py`)
- **Line**: 64
- **Issue**: Accesses `p["contentJson"]` without `.get()` fallback.
- **Impact**: Could crash on malformed `ai_chat.json` entries.
- **Mitigation**: Uncommon — Figma Make exports are generally well-formed.

## When Build Fails (Quick Reference)

1. Check `KNOWN_VERSIONS` pin → change to `latest` in `package.json`
2. Check for string template / dynamic imports missed by regex
3. Check for Figma-specific runtime imports beyond `figma:asset`
4. Check CSS files for `@import url('package')` syntax
