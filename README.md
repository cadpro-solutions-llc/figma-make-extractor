# figma-make-extractor

A [Claude Code](https://claude.ai/code) skill that converts a [Figma Make](https://www.figma.com/make/) `.make` export into a clean, runnable local React + Vite + TypeScript project.

## What it does

Figma Make saves project state in a `.make` archive. This skill unpacks it into a proper local project:

- Full source tree extracted from the Figma Make project
- `package.json` with only the packages your project actually imports — not Figma's 50-package starter list
- Clean Vite + TypeScript scaffolding with no Figma runtime dependency
- `docs/design-brief.md` — the original design brief from the Figma Make session
- `docs/figma-make-history.md` — a readable archive of the full Figma Make chat

The pipeline verifies its work by running `npm install && npm run build` and reports the result.

## Prerequisites

- [Claude Code](https://claude.ai/code) CLI or desktop app
- Node.js ≥ 18
- Python 3.9+
- npm

## Installation

**As a Claude Code skill (recommended)**

Place this directory where Claude Code can find it:

```bash
# Global — available in all your projects
git clone https://github.com/lrenhrda/figma-make-extractor ~/.claude/skills/figma-make-extractor

# Or project-local
git clone https://github.com/lrenhrda/figma-make-extractor .claude/skills/figma-make-extractor
```

Claude Code picks up `SKILL.md` automatically and knows when to invoke the skill.

**Standalone CLI**

You can also run the pipeline directly without Claude Code:

```bash
python3 scripts/extract.py path/to/Project.make path/to/output-dir
```

## Usage

**With Claude Code**

Once installed, just describe what you want:

> "I have a Figma Make file at ~/Downloads/MyProject.make — set it up as a local project in ~/projects/myproject"

**CLI flags**

```bash
# Custom project name (defaults to a slug of the .make filename)
python3 scripts/extract.py Project.make output-dir --name my-project

# Skip npm install + build verification
python3 scripts/extract.py Project.make output-dir --no-build
```

The first run installs three small Node packages (`pako`, `fzstd`, `kiwi-schema`) into `scripts/node_modules/` for the canvas decoder. This takes ~10 seconds and only happens once.

## What you get

```
output-dir/
├── src/               # full component tree, exactly as it was in Figma Make
│   ├── App.tsx
│   ├── main.tsx       # generated Vite entry
│   ├── components/
│   └── styles/
├── package.json       # auto-detected deps only
├── vite.config.ts
├── tsconfig.json
├── index.html
├── README.md
├── CLAUDE.md          # brief orientation for future Claude Code sessions
└── docs/
    ├── design-brief.md        # original Figma Make prompt
    └── figma-make-history.md  # full chat archive
```

Then:

```bash
cd output-dir
npm run dev
```

## How it works

Five stages:

1. **Unzip** — `.make` files are standard ZIP archives
2. **Decode `canvas.fig`** — a custom binary format (Kiwi schema + zstd payload) that holds the final state of every file
3. **Reconstruct** — write every `CODE_FILE` node to disk; strip Figma's pinned-version import specifiers; rewrite `figma:asset/…` imports to `/assets/` URLs
4. **Scaffold** — detect npm imports from source, generate `package.json`, Vite + TypeScript config, and entry point
5. **Docs** — render `README.md`, `CLAUDE.md`, design brief, and chat archive from `ai_chat.json`

The key insight: **`canvas.fig` is the source of truth**, not the chat history. Reconstructing from chat replay misses roughly half the files because Figma seeds projects with starter files that never appear in the chat.

## Attribution

`scripts/decode_canvas.js` is adapted from [albertsikkema/figma-make-extractor](https://github.com/albertsikkema/figma-make-extractor) (MIT, © 2026 Albert Sikkema). The schema decoding logic is unchanged; modifications are CLI argument handling, tolerance for both `fig-makee` and `fig-makej` magic headers, and cleaner error reporting. See [NOTICE](NOTICE) for the full attribution.

## License

MIT — see [LICENSE](LICENSE).
