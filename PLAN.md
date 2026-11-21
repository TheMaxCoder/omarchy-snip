# Snip v1.0 — Implementation Plan

Snip is an Omarchy shell plugin: a keyboard-first picker for saved snippets and
clipboard history. This repository turns the author's personal version (baseline
commit `18131f9`) into a public plugin that works on any Omarchy 4 install via
`omarchy plugin add https://github.com/TheMaxCoder/omarchy-snip`.

The implementer works phase by phase. Each phase ends with all tests passing and
one commit. A reviewer reads the diff between phases.

## Ground rules for the implementer

- Work only inside this repository. Never modify `~/.config/`, `~/.local/`,
  `/usr/share/omarchy/`, Hyprland, or the running shell. Never touch the real
  database at `~/.local/share/snip/`. Tests must use temporary directories through
  the `SNIP_*` environment overrides.
- Do not push, add remotes, or install packages.
- Python: standard library only, Python ≥ 3.10. QML: Quickshell + Omarchy's
  `qs.Commons`/`qs.Ui`, as the baseline already uses. No new runtime dependencies.
- Keep the baseline's architecture: `bin/snip` is a stateless CLI that owns all
  data logic and prints JSON; `Snip.qml` only renders, handles keys, and runs
  commands. Pure JS logic (search, key parsing) lives in `.pragma library` JS
  files so Node can test it.
- Surgical, readable code that matches the baseline style. No features beyond this plan.
- Reference material (read-only) on this machine: `/usr/share/omarchy/shell/`
  (`shell.qml`, `services/PluginRegistry.qml`, `plugins/clipboard/`),
  `/usr/share/omarchy/bin/omarchy-plugin-*`, `/usr/share/omarchy/bin/omarchy-clipboard-paste-*`,
  `/usr/share/omarchy/default/hypr/`.
- Verification commands available: `python3 -m unittest`, `node --test`,
  `/usr/lib/qt6/bin/qmllint` (unresolved `qs.*`/Quickshell imports are expected;
  treat only syntax errors as failures), `omarchy-plugin-validate <dir>`.
- End each phase with: all tests green, `git diff --check` clean, a commit whose
  message names the phase, and a short report: what changed, how it was verified,
  any deviation from this plan and why.

## Verified platform facts (Omarchy 4.0.0.alpha)

- The host injects `omarchyPath`, `shell`, `manifest` (and others) into the
  overlay root if those properties exist (`shell/shell.qml` ~L1406).
  `manifest.__sourceDir` is the plugin's absolute install directory
  (`shell.qml` `publicPluginManifest`, `PluginRegistry.qml` ~L619). Use it to locate `bin/snip`.
- `omarchy-shell shell toggle <id> '{}'` → root `open(payload)` or root
  `close(null)`. The host never calls root `toggle()`. Hyprland binding:
  `o.rebind("SUPER + CTRL + V", "Snip", { panel = "themaxcoder.snip" })`.
- Per-plugin settings are not delivered to overlay plugins, and disabling a plugin
  drops its `shell.json` entry. Snip therefore uses its own config file (below).
- Clipboard history is written by the first-party `omarchy.clipboard` plugin to
  `$HOME/.local/state/omarchy/clipboard-history.json` (XDG_STATE_HOME ignored).
  It holds at most 500 entries, newest first, and drops sensitive entries.
  Text entry: `{"type":"text","text":…}`. Image entry: `{"type":"image","mime","path","capturedAt"}`.
- `omarchy-clipboard-paste-text` accepts text only as a command-line argument (ARG_MAX risk).
  `omarchy-clipboard-paste-file` is just `wl-copy --type MIME < path; sleep 0.15; wtype -M shift -k Insert -m shift`.
- Theme palette file: `~/.local/state/omarchy/current/theme/colors.toml`. The
  `Color` singleton exposes only accent/urgent/muted/foreground/background plus
  surface roles (menu.*). The baseline's colors.toml parsing for green/orange/cyan stays.
- Omarchy's window rules float and center app-id `TUI.float`
  (`default/hypr/apps/system.lua`). Omarchy terminals declare
  `X-TerminalArgAppId`, so `xdg-terminal-exec --app-id=TUI.float --title=… -- cmd…` works with any of them.

## Target repository layout

```
manifest.json          id themaxcoder.snip, author TheMaxCoder, version 1.0.0
Snip.qml               overlay UI
Search.js              fuzzy ranking (.pragma library)
Keys.js                key-spec parsing, matching, keymap merge (.pragma library)
bin/snip               Python CLI backend (executable)
config.example.json    every option with its default
tests/test_backend.py  unittest suite for bin/snip
tests/search.test.mjs  node --test for Search.js
tests/keys.test.mjs    node --test for Keys.js
.github/workflows/ci.yml
README.md  LICENSE  CHANGELOG.md  .gitignore
```

Node tests load the `.js` files with `vm` after stripping the `.pragma library` line.

---

## Phase 1 — Portability and configuration

1. **Identity.** `manifest.json`: id `themaxcoder.snip`, author `TheMaxCoder`,
   description "Keyboard-first snippet and clipboard picker", version `1.0.0`.
   The layer-shell namespace becomes `snip` and the fallback hide id becomes the new id.
2. **Self-locating backend.** Add `property var manifest` (already present) and
   derive `backendPath = manifest.__sourceDir + "/bin/snip"`. Replace every
   `homePath + "/.local/bin/snip"`. If `__sourceDir` is missing, show a clear status error.
3. **Lifecycle.** Implement root `close(payload)` so it clears state the same way
   `dismiss()` does without recursing into `shell.hide`. Keep `open(payload)`.
   Remove the unused `toggle()`, or keep it only if something calls it.
4. **Remove personal code.** Delete `LEGACY_DIR`, `parse_legacy_content`,
   `legacy_documents`, `migrate_legacy`, the `migrate` subcommand, and the call
   that runs migration automatically. Phase 3's `import` replaces them.
5. **Single source for paths.** `snapshot` output gains
   `"clipboardFile": "<absolute path>"`. QML binds its clipboard `FileView.path`
   to that value instead of hardcoding it. The backend default stays
   `$HOME/.local/state/omarchy/clipboard-history.json`, matching Omarchy, with the
   `SNIP_CLIPBOARD_FILE` override.
6. **Config file** at `${XDG_CONFIG_HOME:-~/.config}/snip/config.json`, optional.
   - `bin/snip config` prints the effective merged config as JSON: defaults plus
     the user file, with validation. Unknown keys and bad types produce a warning
     list in the output (`"warnings": [...]`); bad values fall back to the default
     and never crash. Override the path with `SNIP_CONFIG_FILE` for tests.
   - QML loads it through `bin/snip config` on open, and also when a `FileView` on
     the config path reports a change. The path comes from the `config` output.
   - Schema (defaults shown):
     ```json
     {
       "startInSearch": false,
       "terminal": [],
       "editor": "",
       "keys": {
         "up": ["Up", "k"], "down": ["Down", "j"],
         "prevTab": ["Left", "h", "Shift+Tab"], "nextTab": ["Right", "l", "Tab"],
         "first": ["Home", "g"], "last": ["End", "Shift+G"],
         "paste": ["Return", "Enter", "p"], "copy": ["y", "Ctrl+C", "Super+C"],
         "pin": ["f"], "save": ["s"], "edit": ["i"], "delete": ["d"],
         "newTab": ["Shift+N"], "deleteTab": ["Shift+D"],
         "search": ["/"], "back": ["Escape"], "close": ["q"]
       }
     }
     ```
   - An action listed in the user file replaces that action's default list. Other
     actions keep their defaults. An empty list disables the action. Digits 0–9
     always jump to tab N.
7. **Keys.js.**
   - Parse specs: modifiers `Ctrl`, `Alt`, `Shift`, `Super`, joined with `+`,
     then a key. A key is a single printable character or a Qt key name without
     `Key_` (`Up`, `Return`, `Escape`, `Tab`, `Home`, `F1`, …).
   - `matches(event, spec)` compares `event.key`, `event.text`, and
     `event.modifiers`. For a single printable character, match on `event.text`
     so `Shift+G` and `G` both work for an uppercase letter. Document exactly how
     Shift is treated.
   - `actionFor(event, keymap)` returns the first matching action.
   - Detect conflicts (the same spec bound to two actions) and report them in the
     `config` warnings via the backend's duplicate check. Implement the check in
     Python too, or have QML report it as a status. Pick one and document it.
   - Replace every hardcoded key comparison in `Snip.qml` with `actionFor`. Modal
     sub-states (save picker, new-tab input) use `up`/`down`/`paste`/`back` from
     the same keymap.
8. **Search-first mode.** When `startInSearch` is true, `open()` enters search
   mode. `back` (Escape) always steps back one level: clear a non-empty query →
   leave search for navigation → close. Typing in search mode still accepts only
   unmodified printable text. Action keys in search mode are limited to `up`,
   `down`, `paste`, `copy`, and `back`, plus arrow keys. Never treat a letter as an
   action while searching.
9. **Footer hints.** Generate the hint line from the effective keymap, using each
   action's first spec, with readable labels (`↑`, `↵`, `Esc`). Never hardcode it.
10. **Editor launch.**
    - Terminal command: `config.terminal`, a non-empty argv array, if set.
      Otherwise `["xdg-terminal-exec", "--app-id=TUI.float", "--title=Edit Snip", "--"]`.
    - Editor resolution happens inside `bin/snip edit`: `config.editor`, then
      `$VISUAL`, `$EDITOR`, then `nvim`, `vim`, `nano`, whichever exists first.
    - QML runs `terminalArgv + [backendPath, "edit", id]`. If `xdg-terminal-exec`
      is missing and no terminal is configured, show a status error.
11. **Tests.**
    - Convert `tests/test-snip.sh` to `tests/test_backend.py` (unittest,
      subprocess against `bin/snip`, temp dirs through `SNIP_DATA_DIR`,
      `SNIP_CLIPBOARD_FILE`, `SNIP_CONFIG_FILE`, `XDG_RUNTIME_DIR`), keeping every
      existing assertion except the legacy ones. Delete the bash test.
    - Add config merge and validation tests and `tests/keys.test.mjs`.
12. Run `omarchy-plugin-validate .` and qmllint. Commit "Phase 1: portability and configuration".

## Phase 2 — Robustness

1. **Stable clipboard references.**
   - Each inbox entry in `snapshot` gets `"ref"`, the existing `content_hash(kind, body, path)`.
   - Replace `historyIndex` arguments everywhere with `--ref <hash>`:
     `pin-inbox`, `save-inbox`, `save-inbox-new`, and paste.
   - The backend resolves a ref against the current history file. If it is gone,
     exit non-zero with "That clipboard item is no longer in history". Remove
     `historyIndex` from the JSON and the QML.
2. **`snip paste` owns pasting.**
   - Usage: `snip paste (--id N | --ref HASH) [--copy-only]`.
   - Text is written to a 0600 temp file in `$XDG_RUNTIME_DIR`, then
     `wl-copy --type "text/plain;charset=utf-8" < file`. Images:
     `wl-copy --type MIME < path`.
   - Unless copy-only: `sleep 0.15`, then `wtype -M shift -k Insert -m shift`.
   - Delete the temp file in `finally`. Update `last_used_at` for saved items.
   - Snip no longer calls any `omarchy-clipboard-paste-*` script, which removes
     the ARG_MAX limit and an unstable dependency.
   - QML hides first, then `execDetached([backendPath, "paste", …])`. Copy-only
     stays open and shows "Copied".
   - Test: a 1 MB body round-trips through `paste --copy-only`, with `wl-copy`
     stubbed by a fake executable on `PATH` that records its stdin.
3. **Durable saved images.**
   - Saving an image item copies the file to `$DATA_DIR/images/<sha256>.<ext>`
     and stores that path. Omarchy's history images can disappear.
   - Add a schema migration that copies existing image rows still pointing
     outside `$DATA_DIR`, when their source exists.
   - Rows whose file is missing render as "Image file missing" in preview, and
     paste fails with that message.
   - Deleting an item deletes its owned image file when no other row references it.
4. **Schema versioning.**
   - Store `schema_version` in the existing `metadata` table and add an ordered
     migrations list, run in a transaction on connect.
   - The baseline schema is version 1. Phase 2 changes are version 2.
   - Existing databases from the baseline must open, migrate, and keep every row.
     Test this with a fixture DB created by the baseline schema SQL.
5. **Dependency and error handling.**
   - Every subprocess failure, including a missing `wl-copy`, `wtype`, or editor,
     yields one human sentence on stderr and a non-zero exit. QML already shows stderr.
   - `bin/snip doctor` prints a checklist with ✓/✗ and a fix hint per line, and
     exits non-zero if any required check fails:
     - Python version
     - `wl-copy`, `wl-paste`, `wtype` on PATH (required)
     - `xdg-terminal-exec` (warn)
     - clipboard history file exists and parses (warn: "enable omarchy.clipboard")
     - config parses, plus its warnings
     - DB opens, passes `PRAGMA integrity_check`, and is at the current schema version
     - `hyprctl binds -j` contains `themaxcoder.snip` (warn with the README binding line if not, skip if hyprctl is absent)
6. **Concurrency.** Mutations already serialize in QML through `backend.running`.
   Also set `PRAGMA busy_timeout` and use WAL mode, so a detached `paste`/`used`
   racing a `snapshot` never fails.
7. Tests for refs (including a stale ref), paste, images, migration, and doctor
   (with stubbed tools). Commit "Phase 2: robustness".

## Phase 3 — Search, import/export, capture

1. **Fuzzy ranked search in `Search.js`.**
   - `score(query, fields)` returns a number, or -1 for no match.
     - Tokenize the query on whitespace. Every token must match somewhere (AND).
     - Per token, best score across fields, higher first: exact title prefix >
       word-start match in the title > contiguous substring in the title >
       subsequence (fuzzy) in the title > substring in the category > substring
       in the body. Case-insensitive.
     - Recency is the tiebreaker: input order, since the backend already sorts by
       pinned, then last used.
   - `filter(query, rows)` returns rows sorted by score.
   - Search scans at most the first 20,000 characters of each body to keep keystrokes fast.
   - QML search uses it.
   - `tests/search.test.mjs` covers ordering, AND semantics, case, and fuzzy subsequence.
2. **Export** — `snip export --format json|markdown [--output PATH]` (default: stdout for JSON).
   - JSON: `{"format":"snip","version":1,"categories":[…],"items":[…]}` with all
     text fields. Image items carry their path and are skipped with a stderr
     note if `--skip-images` is given. Document that images are referenced, not embedded.
   - Markdown: requires `--output DIR`, writing one `<category>.md` per category
     plus `Pinned.md` for uncategorized items. Each item is `## <title>` followed
     by the body verbatim. Bodies containing lines that start with `## ` get
     wrapped in a fenced block, so the format round-trips. Text items only.
3. **Import** — `snip import PATH`.
   - Accepts a JSON export, a `.md` file, or a directory of `.md` files. The
     category comes from the file name.
   - Deduplicates by content hash. Prints `{"imported": N, "skipped": M}`.
   - Round-trip tests: export then import into an empty DB gives the same items.
4. **Capture.**
   - `snip add` keeps its current behavior (clipboard text) and adds
     `--primary`, which reads the selection via `wl-paste --primary`, and
     `--stdin`.
   - Options: `--category NAME` (created if missing), `--title`, `--pin`.
   - Print the new item as JSON.
   - Send a desktop notification only if `--notify` is passed (via
     `notify-send`, skipped if absent). Document a binding example.
5. Commit "Phase 3: search, import/export, capture".

## Phase 4 — Release readiness

1. **README.md**, user-facing and concise:
   - one-line pitch and a screenshot placeholder `docs/screenshot.png` (the author will capture it)
   - requirements (Omarchy 4, the `omarchy.clipboard` plugin enabled for the Inbox; everything else ships with Omarchy)
   - install: `omarchy plugin add https://github.com/TheMaxCoder/omarchy-snip --enable`
   - binding line for `~/.config/hypr/bindings.lua`, and how to pick another key
   - optional CLI symlink: `ln -s ~/.config/omarchy/plugins/themaxcoder.snip/bin/snip ~/.local/bin/snip`
   - key table generated from the defaults, and the config reference (link `config.example.json`)
   - search-first mode, editing (terminal/editor resolution), import/export, capture
   - `snip doctor`
   - data locations and a privacy note (plaintext SQLite, nothing leaves the machine, sensitive clipboard entries are never captured by Omarchy)
   - update (`omarchy plugin update themaxcoder.snip`), uninstall (and how to delete data)
   - tested Omarchy version (`4.0.0.alpha`), license
2. **LICENSE** — MIT, copyright 2026 TheMaxCoder.
3. **CHANGELOG.md** — Keep a Changelog format, entry `1.0.0`.
4. **`.gitignore`** — `__pycache__/`, `*.pyc`, `node_modules/`.
5. **CI** (`.github/workflows/ci.yml`, on push and pull_request, ubuntu-latest):
   - `python3 -m unittest discover -s tests`
   - `node --test tests/`
   - `python3 -m py_compile bin/snip`
   - JSON validity of `manifest.json` and `config.example.json`
   - Use only preinstalled tools.
6. **Final audit:**
   - grep for `nox`, `/home/`, `F23`, `foot`, `.dotfiles`, personal paths, and
     key letters from the old layout (`o`/`a`/`e` as movement); none may remain.
   - Confirm `bin/snip` is executable in git (`git ls-files -s bin/snip` shows 100755).
   - Run `omarchy-plugin-validate .`.
7. Delete `PLAN.md`. Commit "Phase 4: release readiness".

## Phase 5 — Live trial and cutover (reviewer and author, not the implementer)

Back up the real `snip.db`, then:

1. Symlink the checkout to `~/.config/omarchy/plugins/themaxcoder.snip`.
2. Enable it, and bind it in place of the dotfiles' `nox.snip`.
3. Do a physical test pass on the author's own config. Their custom keymap goes
   in their dotfiles' `~/.config/snip/config.json`.

Then remove `nox.snip` and `~/.local/bin/snip` from the dotfiles, create the
GitHub repository, and push. Each of those steps needs the author's explicit approval.
