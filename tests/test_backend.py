from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SNIP = REPO / "bin/snip"
DEFAULTS = json.loads((REPO / "config.example.json").read_text(encoding="utf-8"))


class BackendTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.history = self.root / "history.json"
        self.config = self.root / "config.json"
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        self.env = {
            **os.environ,
            "HOME": str(self.root),
            "PATH": str(self.bin),
            "SNIP_DATA_DIR": str(self.root / "data"),
            "SNIP_CLIPBOARD_FILE": str(self.history),
            "SNIP_CONFIG_FILE": str(self.config),
            "SNIP_HYPR_DIR": str(self.root / "hypr"),
            "XDG_CONFIG_HOME": str(self.root / "xdg-config"),
            "XDG_STATE_HOME": str(self.root / "xdg-state"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "OMARCHY_PATH": "",
            "VISUAL": "",
            "EDITOR": "",
        }
        self.write_history("clipboard value")

    def run_snip(self, *args, stdin=None):
        return subprocess.run(
            [SNIP, *map(str, args)], cwd=self.root, env=self.env, capture_output=True,
            encoding="utf-8", input=stdin,
        )

    def snip(self, *args, success=True, stdin=None):
        result = self.run_snip(*args, stdin=stdin)
        if not success:
            self.assertNotEqual(result.returncode, 0)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_history(self, *texts):
        self.history.write_text(json.dumps([{"type": "text", "text": text} for text in texts]))

    def ref(self):
        return self.snip("snapshot")["inbox"][0]["ref"]

    def write_image(self):
        source = self.root / "clipboard.png"
        source.write_bytes(b"example image bytes")
        self.history.write_text(json.dumps([{"type": "image", "path": str(source), "mime": "image/png"}]))
        return source

    def write_config(self, value):
        self.config.write_text(json.dumps(value))

    def executable(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + script + "\n")
        path.chmod(0o700)
        return path

    def paste_stub(self, *, bundled=False):
        for name in ("wl-copy", "wtype"):
            self.executable(name, "exit 0")
        directory = self.bin
        if bundled:
            self.env["OMARCHY_PATH"] = str(self.root / "omarchy")
            directory = Path(self.env["OMARCHY_PATH"]) / "bin"
            directory.mkdir(parents=True)
        stub = directory / "omarchy-clipboard-paste-file"
        stub.write_text('''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import stat
import sys
path = Path(sys.argv[-1])
root = Path(os.environ['HOME'])
(root / 'paste-args.json').write_text(json.dumps([sys.argv[1:], stat.S_IMODE(path.stat().st_mode)]))
(root / 'paste-bytes').write_bytes(path.read_bytes())
''')
        stub.chmod(0o700)
        return stub

    def add_text(self, body, category=None, *, pinned=False):
        args = ["--category", category] if category is not None else []
        if pinned:
            args.append("--pin")
        return self.snip("add", "--stdin", *args, stdin=body)

    def tab_orders(self, snapshot=None):
        data = self.snip("snapshot") if snapshot is None else snapshot
        items = data["items"]
        return {
            None: [item["title"] for item in items if item["pinned"]],
            **{tab["name"]: [item["title"] for item in items if item["categoryId"] == tab["id"]]
               for tab in data["categories"]},
        }

    def test_library_workflow(self):
        fresh = self.snip("snapshot")
        self.assertEqual(fresh["categories"], [])
        self.assertEqual(fresh["items"], [])
        category = self.snip("create-category", "Prompts")["id"]
        self.write_history("alpha body", "beta body")
        for entry in self.snip("snapshot")["inbox"]:
            self.snip("save-inbox", "--ref", entry["ref"], category)
        self.write_history("clipboard value")

        snapshot = self.snip("snapshot")
        self.assertEqual(snapshot["categories"][0]["name"], "Prompts")
        self.assertEqual(len(snapshot["items"]), 2)
        self.assertEqual(len(snapshot["inbox"]), 1)
        self.assertEqual(snapshot["clipboardFile"], str(self.history))

        ref = snapshot["inbox"][0]["ref"]
        self.snip("pin-inbox", "--ref", ref)
        snapshot = self.snip("snapshot")
        self.assertEqual(len(snapshot["items"]), 3)
        pinned = [item for item in snapshot["items"] if item["pinned"]]
        self.assertEqual(len(pinned), 1)

        self.snip("toggle-pin", pinned[0]["id"])
        snapshot = self.snip("snapshot")
        self.assertEqual(len(snapshot["items"]), 2)
        self.assertFalse(any(item["pinned"] for item in snapshot["items"]))

        self.snip("save-inbox", "--ref", ref, category)
        snapshot = self.snip("snapshot")
        saved = [item for item in snapshot["items"] if item["body"] == "clipboard value"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["categoryName"], "Prompts")

        self.env["EDITOR"] = str(self.executable(
            "fake-editor", r'''printf '# Edited title\n\nedited body\n' > "$1"'''
        ))
        self.snip("edit", saved[0]["id"])
        snapshot = self.snip("snapshot")
        edited = next(item for item in snapshot["items"] if item["id"] == saved[0]["id"])
        self.assertEqual((edited["title"], edited["body"]), ("Edited title", "edited body"))

        self.snip("create-category", "Later")
        snapshot = self.snip("snapshot")
        self.assertIn("Later", [tab["name"] for tab in snapshot["categories"]])

        self.snip("save-inbox-new", "--ref", ref, "Scratch")
        snapshot = self.snip("snapshot")
        scratch = next(tab for tab in snapshot["categories"] if tab["name"] == "Scratch")
        self.assertTrue(any(item["body"] == "clipboard value" and item["categoryName"] == "Scratch"
                            for item in snapshot["items"]))

        self.snip("delete-category", scratch["id"])
        snapshot = self.snip("snapshot")
        self.assertNotIn("Scratch", [tab["name"] for tab in snapshot["categories"]])
        moved = next(item for item in snapshot["items"] if item["body"] == "clipboard value")
        self.assertTrue(moved["pinned"])
        self.assertIsNone(moved["categoryId"])

        self.snip("delete", moved["id"])
        snapshot = self.snip("snapshot")
        self.assertNotIn(moved["id"], [item["id"] for item in snapshot["items"]])

    def test_clipboard_default_ignores_xdg_state_home(self):
        self.env.pop("SNIP_CLIPBOARD_FILE")
        default_path = self.root / ".local/state/omarchy/clipboard-history.json"
        default_path.parent.mkdir(parents=True)
        default_path.write_text(self.history.read_text())
        snapshot = self.snip("snapshot")
        self.assertEqual(snapshot["clipboardFile"], str(default_path))
        self.assertEqual(snapshot["inbox"][0]["body"], "clipboard value")

    def test_config_defaults_and_paths(self):
        self.env["SNIP_CONFIG_FILE"] = self.config.name
        self.env["SNIP_CLIPBOARD_FILE"] = self.history.name
        config = self.snip("config")
        self.assertEqual({key: config[key] for key in DEFAULTS}, DEFAULTS)
        self.assertEqual(config["warnings"], [])
        self.assertEqual(config["configFile"], str(self.config))
        self.assertFalse(config["hasDefaultTerminal"])
        self.assertFalse(Path(self.env["SNIP_DATA_DIR"]).exists())
        self.assertEqual(self.snip("snapshot")["clipboardFile"], str(self.history))

        self.executable("xdg-terminal-exec", "exit 0")
        self.assertTrue(self.snip("config")["hasDefaultTerminal"])
        self.env.pop("SNIP_CONFIG_FILE")
        xdg_config = Path(self.env["XDG_CONFIG_HOME"]) / "snip/config.json"
        xdg_config.parent.mkdir(parents=True)
        xdg_config.write_text('{"startInSearch": true}')
        config = self.snip("config")
        self.assertEqual(config["configFile"], str(xdg_config))
        self.assertTrue(config["startInSearch"])
        self.env["XDG_CONFIG_HOME"] = ""
        self.assertEqual(self.snip("config")["configFile"], str(self.root / ".config/snip/config.json"))

    def test_config_merges_per_action(self):
        overrides = {
            "startInSearch": True,
            "terminal": ["custom-terminal", "-e"],
            "editor": "my-editor --wait",
            "keys": {"up": ["Ctrl+U"], "down": [], "search": ["Ctrl++"]},
        }
        self.write_config(overrides)
        config = self.snip("config")
        self.assertEqual(config["warnings"], [])
        self.assertEqual(config["keys"], {**DEFAULTS["keys"], **overrides["keys"]})
        for key in ("startInSearch", "terminal", "editor"):
            self.assertEqual(config[key], overrides[key])

    def test_config_warns_and_falls_back_for_invalid_values(self):
        self.write_config({
            "extra": True,
            "startInSearch": 1,
            "terminal": ["terminal", 1],
            "editor": "'unterminated",
            "keys": {"up": "Up", "down": ["Hyper+J"], "paste": ["F2", None],
                     "copy": ["Ctrl+Ctrl+C"], "back": [""], "close": ["Ctrl+"], "noAction": []},
        })
        config = self.snip("config")
        self.assertEqual({key: config[key] for key in DEFAULTS}, DEFAULTS)
        for option in ("extra", "startInSearch", "terminal", "editor", "keys.up", "keys.down",
                       "keys.paste", "keys.copy", "keys.back", "keys.close", "noAction"):
            self.assertTrue(any(option in warning for warning in config["warnings"]), option)

    def test_config_leaves_qt_key_validation_to_overlay(self):
        keys = {"up": ["Foo", "Up"], "back": ["Key_Escape"]}
        self.write_config({"keys": keys})
        config = self.snip("config")
        self.assertEqual(config["keys"], {**DEFAULTS["keys"], **keys})
        self.assertEqual(config["warnings"], [])

    def test_config_handles_unreadable_or_non_object_json(self):
        for data in (b"{", b"\xff", b"[1]", b'{"keys": null}'):
            with self.subTest(data=data):
                self.config.write_bytes(data)
                config = self.snip("config")
                self.assertEqual({key: config[key] for key in DEFAULTS}, DEFAULTS)
                self.assertEqual(len(config["warnings"]), 1)

    def test_config_reports_conflicts_in_default_action_order(self):
        self.write_config({"keys": {"back": ["Backtab"], "down": ["Up", "Alt+Ctrl+X"],
                                    "up": ["Up", "Ctrl+Alt+x"]}})
        config = self.snip("config")
        self.assertEqual(config["keys"]["down"], ["Up", "Alt+Ctrl+X"])
        self.assertEqual(len(config["warnings"]), 3)
        self.assertTrue(all("both up and down; up wins" in warning for warning in config["warnings"][:2]))
        self.assertIn("both prevTab and back; prevTab wins", config["warnings"][2])

    def test_editor_resolution_order_and_temp_file_cleanup(self):
        item_id = self.snip("pin-inbox", "--ref", self.ref())["id"]
        for name in ("visual-editor", "env-editor", "nvim", "vim", "nano"):
            self.executable(name, r'''printf '# Edited\n\n%s\n' "$0" > "$1"''')
        self.executable("config editor", r'''printf '# Edited\n\n%s\n' "$1" > "$2"''')
        self.write_config({"editor": '"config editor" config-won'})
        self.env.update(VISUAL="visual-editor", EDITOR="env-editor")
        for name in ("config editor", "visual-editor", "env-editor", "nvim", "vim", "nano"):
            with self.subTest(editor=name):
                self.snip("edit", item_id)
                expected = "config-won" if name == "config editor" else str(self.bin / name)
                self.assertEqual(self.snip("snapshot")["items"][0]["body"], expected)
                self.assertEqual(list(self.runtime.iterdir()), [])
                (self.bin / name).unlink()
        self.assertIn("No editor found", self.snip("edit", item_id, success=False))

    def test_edit_does_not_overwrite_a_snippet_that_reused_the_id(self):
        item_id = self.snip("pin-inbox", "--ref", self.ref())["id"]
        self.env["EDITOR"] = str(self.executable("racing-editor", f'''
"{SNIP}" delete {item_id} >/dev/null
printf 'newer snippet' | "{SNIP}" add --stdin --title Newer >/dev/null
printf '# Edited\\n\\nedited text\\n' > "$1"'''))
        self.assertIn("changed or was deleted", self.snip("edit", item_id, success=False))
        (item,) = self.snip("snapshot")["items"]
        self.assertEqual((item["id"], item["body"]), (item_id, "newer snippet"))
        (kept,) = self.runtime.iterdir()
        self.assertIn("edited text", kept.read_text())

    def test_refs_survive_reordering_and_stale_refs_are_rejected(self):
        ref = self.ref()
        self.assertEqual(ref, hashlib.sha256(b"text\0clipboard value").hexdigest())
        self.assertNotIn("historyIndex", self.snip("snapshot")["inbox"][0])
        self.write_history("new clipboard entry", "clipboard value")
        self.snip("pin-inbox", "--ref", ref)
        self.assertEqual(self.snip("snapshot")["items"][0]["body"], "clipboard value")
        category = self.snip("create-category", "Existing")["id"]
        self.write_history("new clipboard entry")
        for command in (("pin-inbox",), ("save-inbox", category), ("save-inbox-new", "Stale"), ("paste",)):
            with self.subTest(command=command):
                error = self.snip(command[0], "--ref", ref, *command[1:], success=False)
                self.assertEqual(error.strip(), "snip: That clipboard item is no longer in history")
        self.assertEqual([tab["name"] for tab in self.snip("snapshot")["categories"]], ["Existing"])

    def test_large_text_paste_uses_private_temp_file_and_updates_last_used(self):
        bundled = self.paste_stub(bundled=True)
        self.executable(bundled.name, "exit 99")
        body = "é" * (512 * 1024 - 1) + "\n\n"
        self.write_history(body)
        ref = self.ref()
        self.snip("paste", "--ref", ref, "--copy-only")
        argv, mode = json.loads((self.root / "paste-args.json").read_text())
        self.assertEqual(argv[:2], ["--copy-only", "text/plain;charset=utf-8"])
        self.assertEqual(Path(argv[2]).parent, self.runtime)
        self.assertEqual(mode, 0o600)
        self.assertEqual((self.root / "paste-bytes").read_bytes(), body.encode())
        self.assertFalse(Path(argv[2]).exists())
        item_id = self.snip("pin-inbox", "--ref", ref)["id"]
        self.env.pop("XDG_RUNTIME_DIR")
        self.env["TMPDIR"] = str(self.root)
        self.snip("paste", "--id", item_id)
        argv, _ = json.loads((self.root / "paste-args.json").read_text())
        self.assertEqual(argv[0], "text/plain;charset=utf-8")
        self.assertEqual(Path(argv[1]).parent, self.root)
        self.assertFalse(Path(argv[1]).exists())
        with closing(sqlite3.connect(Path(self.env["SNIP_DATA_DIR"]) / "snip.db")) as db:
            stamp = db.execute("SELECT last_used_at FROM items WHERE id = ?", (item_id,)).fetchone()[0]
        self.assertIsNotNone(stamp)

    def test_paste_failures_are_one_line_and_clean_up(self):
        ref = self.ref()
        self.assertIn("omarchy-clipboard-paste-file not found", self.snip("paste", "--ref", ref, success=False))
        stub = self.paste_stub()
        (self.bin / "wl-copy").unlink()
        self.assertIn("wl-copy not found", self.snip("paste", "--ref", ref, success=False))
        self.executable("wl-copy", "exit 0")
        (self.bin / "wtype").unlink()
        self.assertIn("wtype not found", self.snip("paste", "--ref", ref, success=False))
        for status in (0, 7):
            self.executable(stub.name, f"printf 'error\\nextra\\n' >&2; exit {status}")
            error = self.snip("paste", "--ref", ref, "--copy-only", success=False)
            self.assertEqual(error.splitlines(), ["snip: Omarchy could not copy the item; check wl-copy"])
            self.assertEqual(list(self.runtime.iterdir()), [])
        for selectors in ((), ("--ref", ref, "--id", 1)):
            self.assertNotEqual(self.run_snip("paste", *selectors).returncode, 0)

    def test_only_non_copy_paste_failures_notify(self):
        notice = self.root / "notification"
        self.executable("notify-send", '''printf '%s\\n' "$@" > "$HOME/notification"
printf 'ignore this error\\n' >&2
exit 1''')
        message = "That clipboard item is no longer in history"
        self.assertEqual(self.snip("paste", "--ref", "stale", "--copy-only", success=False).strip(),
                         f"snip: {message}")
        self.assertFalse(notice.exists())
        self.assertEqual(self.snip("paste", "--ref", "stale", success=False).splitlines(),
                         [f"snip: {message}"])
        self.assertEqual(notice.read_text().splitlines(), ["-a", "Snip", "Snip could not paste", message])
        notice.unlink()
        self.paste_stub()
        self.snip("paste", "--ref", self.ref())
        self.assertFalse(notice.exists())

    def test_image_is_linked_and_pastes_after_source_is_deleted(self):
        self.paste_stub()
        source = self.write_image()
        ref = self.ref()
        self.assertEqual(ref, hashlib.sha256(f"image\0{source}".encode()).hexdigest())
        self.snip("paste", "--ref", ref)
        argv, _ = json.loads((self.root / "paste-args.json").read_text())
        self.assertEqual(argv, ["image/png", str(source)])
        item_id = self.snip("pin-inbox", "--ref", ref)["id"]
        item = self.snip("snapshot")["items"][0]
        owned = Path(item["path"])
        self.assertEqual(owned, Path(self.env["SNIP_DATA_DIR"]) / "images" / f"{ref}.png")
        self.assertTrue(owned.samefile(source))
        data = source.read_bytes()
        source.unlink()
        snapshot = self.snip("snapshot")
        self.assertTrue(snapshot["inbox"][0]["imageMissing"])
        self.assertFalse(snapshot["items"][0]["imageMissing"])
        self.snip("paste", "--id", item_id, "--copy-only")
        argv, _ = json.loads((self.root / "paste-args.json").read_text())
        self.assertEqual(argv, ["--copy-only", "image/png", str(owned)])
        self.assertEqual((self.root / "paste-bytes").read_bytes(), data)
        self.snip("toggle-pin", item_id)
        self.assertFalse(owned.exists())
        self.assertEqual(self.snip("snapshot")["items"], [])

    def test_deleting_a_shared_image_only_unlinks_last_reference(self):
        source = self.write_image()
        item_id = self.snip("pin-inbox", "--ref", self.ref())["id"]
        owned = Path(self.snip("snapshot")["items"][0]["path"])
        with closing(sqlite3.connect(Path(self.env["SNIP_DATA_DIR"]) / "snip.db")) as db, db:
            cursor = db.execute(
                "INSERT INTO items(kind, title, path, content_hash, position) VALUES ('image', ?, ?, ?, 1)",
                ("Also used", str(owned), "fixture-hash"),
            )
            other_id = cursor.lastrowid
        self.snip("delete", item_id)
        self.assertTrue(owned.samefile(source))
        self.snip("delete", other_id)
        self.assertFalse(owned.exists())
        self.assertTrue(source.is_file())

    def test_missing_saved_image_is_reported(self):
        self.write_image()
        item_id = self.snip("pin-inbox", "--ref", self.ref())["id"]
        Path(self.snip("snapshot")["items"][0]["path"]).unlink()
        self.assertTrue(self.snip("snapshot")["items"][0]["imageMissing"])
        error = self.snip("paste", "--id", item_id, success=False)
        self.assertEqual(error.strip(), "snip: Image file missing")
        self.snip("delete", item_id)

    def test_image_link_falls_back_to_copy_only_for_exdev_or_eperm(self):
        source = self.write_image()
        ref = self.ref()
        for error in (errno.EXDEV, errno.EPERM, errno.EACCES):
            with self.subTest(error=error):
                code = '''
import os, runpy, sys
from unittest.mock import patch
error, *sys.argv = sys.argv[1:]
with patch.object(os, 'link', side_effect=OSError(int(error), os.strerror(int(error)))):
    runpy.run_path(sys.argv[0], run_name='__main__')
'''
                result = subprocess.run([sys.executable, "-c", code, str(error), SNIP, "pin-inbox", "--ref", ref],
                                        cwd=self.root, env=self.env, capture_output=True, text=True)
                if error == errno.EACCES:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.snip("snapshot")["items"], [])
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                item = self.snip("snapshot")["items"][0]
                owned = Path(item["path"])
                self.assertFalse(owned.samefile(source))
                self.assertEqual(owned.read_bytes(), source.read_bytes())
                self.snip("delete", item["id"])

    def test_baseline_database_migrates_in_place_and_preserves_rows(self):
        source = self.write_image()
        data_dir = Path(self.env["SNIP_DATA_DIR"])
        data_dir.mkdir()
        missing = str(self.root / "missing.png")
        original = [(10, "text", "Snippet", "example", "", "text/plain", "fixture-text", 1),
                    (11, "image", "Screenshot", "", str(source), "image/png", hashlib.sha256(f"image\0{source}".encode()).hexdigest(), 0),
                    (12, "image", "Missing", "", missing, "image/png", hashlib.sha256(f"image\0{missing}".encode()).hexdigest(), 1)]
        with closing(sqlite3.connect(data_dir / "snip.db")) as db:
            db.executescript((REPO / "tests/baseline-schema.sql").read_text())
            with db:
                db.execute("INSERT INTO categories(id, name, sort_order) VALUES (4, 'Examples', 1)")
                db.execute("INSERT INTO metadata VALUES ('legacy_migrated', '2026-01-01')")
                db.executemany("INSERT INTO items(id, kind, title, body, path, mime, content_hash, pinned, category_id) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 4)", original)
            snapshot = self.snip("snapshot")
            self.assertEqual(snapshot["categories"], [{"id": 4, "name": "Examples", "sortOrder": 1}])
            self.assertEqual(len(snapshot["items"]), len(original))
            rows = db.execute("SELECT id, kind, title, body, path, mime, content_hash, pinned FROM items ORDER BY id").fetchall()
            self.assertEqual(rows[0], original[0])
            self.assertEqual(rows[2], original[2])
            owned = Path(rows[1][4])
            self.assertTrue(owned.is_relative_to(data_dir / "images"))
            self.assertTrue(owned.samefile(source))
            self.assertEqual(rows[1], (*original[1][:4], str(owned), *original[1][5:]))
            self.assertEqual(dict(db.execute("SELECT key, value FROM metadata")),
                             {"legacy_migrated": "2026-01-01", "schema_version": "3"})
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(self.snip("snapshot"), snapshot)

    def test_schema_2_migration_preserves_order_in_every_tab(self):
        data_dir = Path(self.env["SNIP_DATA_DIR"])
        data_dir.mkdir()
        earlier, later = "2026-01-01 00:00:00", "2026-01-02 00:00:00"
        with closing(sqlite3.connect(data_dir / "snip.db")) as db:
            db.executescript((REPO / "tests/baseline-schema.sql").read_text())
            with db:
                # Version 2 moved image files; its table definitions are still the baseline's.
                db.execute("INSERT INTO metadata VALUES ('schema_version', '2')")
                db.execute("INSERT INTO categories(id, name, sort_order) VALUES (1, 'A', 1), (2, 'B', 2)")
                db.executemany(
                    "INSERT INTO items(id, category_id, kind, title, content_hash, pinned, updated_at, last_used_at) "
                    "VALUES (?, ?, 'text', ?, ?, ?, ?, ?)",
                    [(1, 1, "Used", "a", 1, earlier, later),
                     (2, 2, "Pinned only by flag", "b", 1, later, None),
                     (3, 1, "Edited after use", "c", 1, later, earlier),
                     (4, 1, "Older ID", "d", 0, later, None),
                     (5, 1, "Newer ID", "e", 0, later, None),
                     (6, 2, "Other tab", "f", 0, later, None)],
                )
            migrated = self.snip("snapshot")
            self.assertEqual(self.tab_orders(migrated), {
                None: ["Pinned only by flag", "Used", "Edited after use"],
                "A": ["Used", "Edited after use", "Newer ID", "Older ID"],
                "B": ["Pinned only by flag", "Other tab"],
            })
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone(), ("3",))
            self.assertEqual(self.snip("snapshot"), migrated)

    def test_snapshot_refuses_future_and_unreadable_schema(self):
        data_dir = Path(self.env["SNIP_DATA_DIR"])
        data_dir.mkdir()
        database = data_dir / "snip.db"
        database.write_bytes(b"not a database")
        self.assertEqual(self.snip("snapshot", success=False).splitlines(), ["snip: file is not a database"])
        database.unlink()
        with closing(sqlite3.connect(database)) as db:
            db.executescript("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                             "INSERT INTO metadata VALUES ('schema_version', '99');")
            self.assertEqual(self.snip("snapshot", success=False).splitlines(),
                             ["snip: Unsupported Snip schema version 99"])
            self.assertEqual(db.execute("SELECT value FROM metadata").fetchone(), ("99",))

    def test_new_and_resaved_items_go_to_the_top_of_their_group(self):
        older = self.add_text("Older", "Work")
        self.add_text("Pinned", "Work", pinned=True)
        self.add_text("Newer", "Work")
        self.assertEqual(self.tab_orders()["Work"], ["Pinned", "Newer", "Older"])
        self.snip("used", older["id"])
        self.assertEqual(self.add_text("Older", "Work")["id"], older["id"])
        self.assertEqual(self.tab_orders()["Work"], ["Pinned", "Older", "Newer"])

        self.write_history("First Inbox", "Second Inbox", "Older", "Pinned")
        refs = {row["title"]: row["ref"] for row in self.snip("snapshot")["inbox"]}
        self.snip("save-inbox-new", "--ref", refs["First Inbox"], "New tab")
        self.snip("save-inbox-new", "--ref", refs["Second Inbox"], "New tab")
        self.assertEqual(self.tab_orders()["New tab"], ["Second Inbox", "First Inbox"])
        for title in ("First Inbox", "Older"):
            self.snip("save-inbox", "--ref", refs[title], older["categoryId"])
        self.assertEqual(self.tab_orders()["Work"], ["Pinned", "Older", "First Inbox", "Newer"])
        self.snip("pin-inbox", "--ref", refs["Second Inbox"])
        self.assertEqual(self.tab_orders()[None], ["Second Inbox", "Pinned"])
        self.snip("pin-inbox", "--ref", refs["Pinned"])
        self.assertEqual(self.tab_orders()[None], ["Pinned", "Second Inbox"])
        self.snip("save-inbox", "--ref", refs["Second Inbox"], older["categoryId"])
        self.assertEqual(self.tab_orders()["Work"], ["Second Inbox", "Pinned", "Older", "First Inbox", "Newer"])

    def test_pin_and_unpin_go_to_the_top_of_the_destination_group(self):
        item = self.add_text("Move me", "Work")
        self.add_text("Unpinned", "Work")
        self.add_text("Work pin", "Work", pinned=True)
        outside = self.add_text("Pinned only")
        self.snip("toggle-pin", item["id"])
        self.assertEqual(self.tab_orders(), {
            None: ["Move me", "Pinned only", "Work pin"], "Work": ["Move me", "Work pin", "Unpinned"],
        })
        self.snip("toggle-pin", item["id"])
        self.assertEqual(self.tab_orders()["Work"], ["Work pin", "Move me", "Unpinned"])
        self.snip("toggle-pin", outside["id"])
        self.assertEqual(self.tab_orders()[None], ["Work pin"])
        self.assertNotIn(outside["id"], [row["id"] for row in self.snip("snapshot")["items"]])

    def test_use_paste_copy_and_edit_do_not_reorder(self):
        item = self.add_text("First", "Work")
        second = self.add_text("Second", "Work")
        self.add_text("Third", "Work")
        self.paste_stub()
        for args in (("used", item["id"]), ("paste", "--id", second["id"], "--copy-only"),
                     ("paste", "--id", item["id"])):
            self.snip(*args)
            self.assertEqual(self.tab_orders()["Work"], ["Third", "Second", "First"])
        self.env["EDITOR"] = str(self.executable(
            "fake-editor", r'''printf '# Edited\n\nNew body\n' > "$1"'''
        ))
        self.snip("edit", item["id"])
        self.assertEqual(self.tab_orders()["Work"], ["Third", "Second", "Edited"])

    def test_swap_returns_snapshot_and_leaves_other_items_in_relative_order(self):
        first = self.add_text("A", "Work", pinned=True)
        self.add_text("B", "Other", pinned=True)
        second = self.add_text("C", "Work", pinned=True)
        self.add_text("D", "Other", pinned=True)
        unpinned = self.add_text("E", "Work")
        before = self.snip("snapshot")
        for args, error in (
            ((first["id"], 99), "snippet no longer exists"),
            ((2**63, second["id"]), "snippet no longer exists"),
            ((first["id"], first["id"]), "choose two different snippets to swap"),
            ((second["id"], unpinned["id"]), "cannot swap pinned and unpinned snippets"),
        ):
            rejected = self.run_snip("swap-order", *args)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(rejected.stdout, "")
            self.assertEqual(rejected.stderr.splitlines(), [f"snip: {error}"])
            self.assertEqual(self.snip("snapshot"), before)
        swapped = self.snip("swap-order", first["id"], second["id"])
        self.assertEqual(swapped, self.snip("snapshot"))
        self.assertEqual(self.tab_orders(swapped), {
            None: ["D", "A", "B", "C"], "Work": ["A", "C", "E"], "Other": ["D", "B"],
        })

    def test_deleted_tab_moves_to_pinned_as_a_block_in_display_order(self):
        first = self.add_text("Pin 1", "Work", pinned=True)
        second = self.add_text("Pin 2", "Work", pinned=True)
        self.add_text("Unpinned 1", "Work")
        self.add_text("Unpinned 2", "Work")
        self.add_text("Keep 1", "Other", pinned=True)
        self.add_text("Keep 2")
        self.snip("swap-order", first["id"], second["id"])
        moved = self.tab_orders()["Work"]
        self.assertEqual(self.snip("delete-category", first["categoryId"])["moved"], len(moved))
        self.assertEqual(self.tab_orders(), {None: moved + ["Keep 2", "Keep 1"], "Other": ["Keep 1"]})

    def test_positions_are_unique_after_import_and_concurrent_writes(self):
        titles = [f"Imported {index}" for index in range(128)]
        source = self.root / "Work.md"
        source.write_text("".join(f"## {title}\n{title} body\n\n" for title in titles))
        self.assertEqual(self.snip("import", source), {"imported": len(titles), "skipped": 0})
        first, second = [item["id"] for item in self.snip("snapshot")["items"][:2]]
        with ThreadPoolExecutor(max_workers=6) as pool:
            inserts = [pool.submit(self.add_text, f"Added {index}", "Work") for index in range(16)]
            swaps = [pool.submit(self.snip, "swap-order", first, second) for _ in range(5)]
            for task in inserts + swaps:
                task.result()
        self.assertEqual(self.tab_orders()["Work"][16:], [titles[1], titles[0], *titles[2:]])
        swapped = self.snip("swap-order", first, second)
        self.assertEqual(self.tab_orders(swapped)["Work"][16:], titles)
        with closing(sqlite3.connect(Path(self.env["SNIP_DATA_DIR"]) / "snip.db")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*), COUNT(DISTINCT position) FROM items").fetchone(), (144, 144))
            with self.assertRaises(sqlite3.IntegrityError), db:
                db.execute("UPDATE items SET position = (SELECT position FROM items WHERE id = ?) WHERE id = ?",
                           (first, second))

    def test_doctor_reports_requirements_and_nonfatal_warnings(self):
        self.paste_stub(bundled=True)
        self.executable("wl-paste", "exit 0")
        self.executable("xdg-terminal-exec", "exit 0")
        hypr = Path(self.env["SNIP_HYPR_DIR"])
        hypr.mkdir()
        extras = self.root / "extras"
        extras.mkdir()
        (hypr / "linked").symlink_to(extras, target_is_directory=True)
        (extras / "cycle").symlink_to(hypr, target_is_directory=True)
        binding = extras / "bindings.lua"
        binding.write_text('o.rebind("SUPER + CTRL + V", "Snip", { panel = "themaxcoder.snip" })')
        result = self.run_snip("doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for label in ("Python", "omarchy-clipboard-paste-file", "wl-copy", "wl-paste", "wtype",
                      "xdg-terminal-exec", "Clipboard history", "Config", "Database (schema 3)", "Hyprland binding"):
            self.assertIn(f"✓ {label}", result.stdout)

        self.history.write_text("not JSON")
        self.write_config({"unknown": True})
        (self.bin / "xdg-terminal-exec").unlink()
        binding.write_text('local panel = "themaxcoder.snip.old"')
        (hypr / "ignored.txt").write_text("themaxcoder.snip")
        (hypr / "broken.conf").symlink_to(self.root / "missing.conf")
        result = self.run_snip("doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for message in ("✗ xdg-terminal-exec", "Enable omarchy.clipboard", "✗ Config warning",
                        'o.rebind("SUPER + CTRL + V", "Snip", { panel = "themaxcoder.snip" })'):
            self.assertIn(message, result.stdout)
        self.assertIn("✗ Hyprland binding", result.stdout)

        self.env.pop("SNIP_HYPR_DIR")
        default_hypr = Path(self.env["XDG_CONFIG_HOME"]) / "hypr"
        default_hypr.mkdir(parents=True)
        conf = extras / "defaults.conf"
        conf.write_text("bind = SUPER CTRL, V, exec, omarchy-shell shell toggle themaxcoder.snip {}")
        (default_hypr / "bindings.conf").symlink_to(conf)
        self.assertIn("✓ Hyprland binding", self.run_snip("doctor").stdout)
        self.env["XDG_CONFIG_HOME"] = ""
        (self.root / ".config").mkdir()
        (self.root / ".config/hypr").symlink_to(default_hypr, target_is_directory=True)
        self.assertIn("✓ Hyprland binding", self.run_snip("doctor").stdout)

    def test_doctor_fails_without_requirements_or_on_broken_config_and_db(self):
        self.config.write_text("{")
        data_dir = Path(self.env["SNIP_DATA_DIR"])
        data_dir.mkdir()
        (data_dir / "snip.db").write_text("not a database")
        result = self.run_snip("doctor")
        self.assertNotEqual(result.returncode, 0)
        for label in ("omarchy-clipboard-paste-file", "wl-copy", "wl-paste", "wtype", "Config", "Database (schema 3)"):
            self.assertIn(f"✗ {label} — ", result.stdout)

    def test_snapshots_and_last_used_writes_can_race(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            fresh = list(pool.map(lambda _: self.snip("snapshot"), range(6)))
            self.assertTrue(all(snapshot == fresh[0] for snapshot in fresh))
            item_id = self.snip("pin-inbox", "--ref", fresh[0]["inbox"][0]["ref"])["id"]
            self.paste_stub()
            commands = [("snapshot",), ("used", item_id), ("paste", "--id", item_id)] * 4
            list(pool.map(lambda args: self.snip(*args), commands))

    def test_editor_and_clipboard_capture_fail_with_one_line(self):
        item_id = self.snip("pin-inbox", "--ref", self.ref())["id"]
        self.env["EDITOR"] = str(self.executable("bad-editor", "printf 'line1\\nline2\\n' >&2; exit 17"))
        self.assertEqual(self.snip("edit", item_id, success=False).splitlines(),
                         ["snip: The editor could not finish editing the snippet"])
        self.assertEqual(list(self.runtime.iterdir()), [])
        self.assertIn("wl-paste not found", self.snip("add", "--title", "Fail", success=False))
        self.executable("wl-paste", "printf 'line1\\nline2\\n' >&2; exit 17")
        self.assertEqual(self.snip("add", "--title", "Fail", success=False).splitlines(),
                         ["snip: Could not read text from the clipboard with wl-paste"])

    def test_capture_clipboard_primary_and_stdin(self):
        self.executable("wl-paste", '''printf '%s\\n' "$@" > "$HOME/wl-paste-args"
case "$*" in *--primary*) printf 'selection text' ;; *) printf 'clipboard text' ;; esac''')
        clipboard = self.snip("add")
        self.assertEqual((clipboard["title"], clipboard["body"]), ("clipboard text", "clipboard text"))
        self.assertIsNone(clipboard["categoryId"])
        self.assertTrue(clipboard["pinned"])
        self.assertEqual(self.snip("snapshot")["categories"], [])
        self.assertEqual((self.root / "wl-paste-args").read_text().splitlines(),
                         ["--type", "text", "--no-newline"])
        primary = self.snip("add", "--primary", "--category", "Examples", "--title", "Selection")
        self.assertEqual((primary["title"], primary["body"]), ("Selection", "selection text"))
        self.assertIsNotNone(primary["categoryId"])
        self.assertFalse(primary["pinned"])
        self.assertIn("--primary", (self.root / "wl-paste-args").read_text().splitlines())
        (self.bin / "wl-paste").unlink()
        body = "\n# Démo\r\nline two\n\n"
        stdin_item = self.snip("add", "--stdin", "--category", "examples", "--pin", stdin=body)
        self.assertEqual(stdin_item["categoryId"], primary["categoryId"])
        self.assertEqual((stdin_item["title"], stdin_item["body"]), ("Démo", body[:-1]))
        self.assertTrue(stdin_item["pinned"])
        promoted = self.snip("add", "--stdin", stdin="selection text")
        self.assertEqual(promoted["id"], primary["id"])
        self.assertTrue(promoted["pinned"])
        self.assertIsNone(promoted["categoryId"])
        self.assertIn("No text to save", self.snip("add", "--stdin", stdin="\n ", success=False))
        self.assertNotEqual(self.run_snip("add", "--stdin", "--primary", stdin="x").returncode, 0)

    def test_capture_stdin_strips_exactly_one_trailing_newline(self):
        for source, expected in (
            ("snippet\n", "snippet"),
            ("snippet\r\n", "snippet"),
            ("snippet\n\n", "snippet\n"),
            ("snippet\r\n\r\n", "snippet\r\n"),
            ("snippet\r", "snippet\r"),
            ("snippet  \n", "snippet  "),
            ("snippet", "snippet"),
        ):
            with self.subTest(source=source):
                item = self.snip("add", "--stdin", stdin=source)
                self.assertEqual(item["body"], expected)
        self.paste_stub()
        item = self.snip("add", "--stdin", stdin="ready to paste\r\n")
        self.snip("paste", "--id", item["id"], "--copy-only")
        self.assertEqual((self.root / "paste-bytes").read_bytes(), b"ready to paste")

    def test_capture_notification_is_opt_in_and_optional(self):
        self.snip("add", "--stdin", "--notify", stdin="No notifier")
        self.executable("notify-send", '''printf '%s\\n' "$@" > "$HOME/notification"
exit 1''')
        notice = self.root / "notification"
        self.snip("add", "--stdin", stdin="Quiet")
        self.assertFalse(notice.exists())
        item = self.snip("add", "--stdin", "--notify", "--title", "Example", stdin="Private body")
        self.assertEqual(item["title"], "Example")
        self.assertEqual(notice.read_text().splitlines(), ["-a", "Snip", "Snip saved a snippet", "Example"])

    def test_json_round_trip_preserves_text_and_references_images(self):
        first = self.snip("add", "--stdin", "--category", "Examples", "--title", "Café", stdin="\nbody\r\n\n\n")
        self.snip("used", first["id"])
        self.snip("add", "--stdin", stdin="Uncategorized")
        self.snip("add", "--stdin", stdin="Another pinned item")
        self.snip("create-category", "Empty")
        with closing(sqlite3.connect(Path(self.env["SNIP_DATA_DIR"]) / "snip.db")) as db, db:
            db.execute("UPDATE items SET updated_at = '2026-01-01 00:00:00' WHERE pinned = 1")
        source = self.write_image()
        image = self.snip("save-inbox-new", "--ref", self.ref(), "Screenshots")
        exported = self.snip("export", "--format", "json")
        self.assertEqual((exported["format"], exported["version"]), ("snip", 1))
        image_record = next(item for item in exported["items"] if item["id"] == image["id"])
        self.assertTrue(Path(image_record["path"]).samefile(source))
        self.assertEqual((image_record["mime"], image_record["body"]), ("image/png", ""))
        skip = self.run_snip("export", "--skip-images")
        self.assertEqual(skip.returncode, 0, skip.stderr)
        self.assertIn("Skipped 1 image", skip.stderr)
        self.assertEqual([item["kind"] for item in json.loads(skip.stdout)["items"]], ["text"] * 3)

        output = self.root / "backup.json"
        result = self.run_snip("export", "--output", output)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.assertEqual(json.loads(output.read_text()), exported)
        self.assertEqual(self.snip("import", output), {"imported": 0, "skipped": 4})
        self.env["SNIP_DATA_DIR"] = str(self.root / "restored")
        self.assertEqual(self.snip("import", output), {"imported": 4, "skipped": 0})
        self.assertEqual(self.snip("import", output), {"imported": 0, "skipped": 4})
        restored = self.snip("export")
        self.assertEqual([item["contentHash"] for item in restored["items"]],
                         [item["contentHash"] for item in exported["items"]])
        self.assertEqual([tab["name"] for tab in restored["categories"]], ["Examples", "Empty", "Screenshots"])
        from_backup = {item["contentHash"]: item for item in exported["items"]}
        for item in restored["items"]:
            expected = from_backup.pop(item["contentHash"]).copy()
            for row in (item, expected):
                row.pop("id")
            if item["kind"] == "image":
                self.assertTrue(Path(item.pop("path")).samefile(expected.pop("path")))
            self.assertEqual(item, expected)
        self.assertFalse(from_backup)

    def test_json_preserves_swapped_order_and_prepends_only_new_items(self):
        first = self.add_text("A", "Work", pinned=True)
        self.add_text("B", "Other", pinned=True)
        second = self.add_text("C", "Work", pinned=True)
        third = self.add_text("D", "Work")
        fourth = self.add_text("E", "Work")
        self.snip("swap-order", first["id"], second["id"])
        self.snip("swap-order", third["id"], fourth["id"])
        source = self.root / "ordered.json"
        result = self.run_snip("export", "--output", source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([item["title"] for item in json.loads(source.read_text())["items"]], list("ABCDE"))
        expected = self.tab_orders()

        self.env["SNIP_DATA_DIR"] = str(self.root / "empty")
        self.assertEqual(self.snip("import", source), {"imported": 5, "skipped": 0})
        self.assertEqual(self.tab_orders(), expected)

        self.env["SNIP_DATA_DIR"] = str(self.root / "existing")
        self.add_text("A", "Other", pinned=True)
        self.add_text("Keep pinned", "Work", pinned=True)
        self.add_text("D", "Work")
        self.add_text("Keep unpinned", "Work")
        self.assertEqual(self.snip("import", source), {"imported": 3, "skipped": 2})
        self.assertEqual(self.tab_orders(), {
            None: ["B", "C", "Keep pinned", "A"],
            "Work": ["C", "Keep pinned", "E", "Keep unpinned", "D"], "Other": ["B", "A"],
        })

    def test_markdown_round_trip_preserves_verbatim_bodies(self):
        examples = ["Short text", "\n## Nested heading\n```\ntext in code\n```\n\n",
                    "\nonly a leading newline and CRLF\r\n  ", "```unclosed\nplain text", "## Heading at start"]
        example_ids = []
        for index, body in enumerate(examples):
            item = self.snip("add", "--stdin", "--category", "Café notes", "--title", f"Example {index}", stdin=body + "\n")
            example_ids.append(item["id"])
        self.snip("swap-order", example_ids[0], example_ids[2])
        self.snip("toggle-pin", example_ids[1])
        example_order = ["Example 1", "Example 4", "Example 3", "Example 0", "Example 2"]
        self.snip("add", "--stdin", "--category", "Pinned", "--title", "Categorized", stdin="named Pinned")
        title = "Separator & &#10;\r\nSecond line"
        self.snip("add", "--stdin", "--category", "A/B%20", "--title", title, stdin="category path")
        self.snip("add", "--stdin", "--title", "Uncategorized", stdin="pinned note")
        self.snip("pin-inbox", "--ref", self.ref())
        self.write_image()
        self.snip("pin-inbox", "--ref", self.ref())
        directory = self.root / "markdown"
        self.assertIn("requires --output DIR", self.snip("export", "--format", "markdown", success=False))
        result = self.run_snip("export", "--format", "markdown", "--output", directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({file.name for file in directory.iterdir()},
                         {"Café notes.md", "%50inned.md", "A%2FB%2520.md", "Pinned.md"})
        md = (directory / "Café notes.md").read_bytes().decode("utf-8")
        self.assertEqual([line[3:] for line in md.splitlines() if line.startswith("## Example ")], example_order)
        self.assertIn("## Example 0\nShort text\n\n", md)
        self.assertIn("````snip\n" + examples[1] + "\n````", md)
        self.assertNotIn("Screenshot", (directory / "Pinned.md").read_text())

        self.env["SNIP_DATA_DIR"] = str(self.root / "restored")
        self.assertEqual(self.snip("import", directory), {"imported": 9, "skipped": 0})
        self.assertEqual(self.snip("import", directory), {"imported": 0, "skipped": 9})
        restored = self.snip("snapshot")
        self.assertEqual(self.tab_orders(restored)["Café notes"], example_order)
        saved = {item["title"]: item for item in restored["items"]}
        self.assertFalse(saved["Example 1"]["pinned"])
        for index, body in enumerate(examples):
            item = saved[f"Example {index}"]
            self.assertEqual(item["body"], body)
            self.assertEqual(item["categoryName"], "Café notes")
        self.assertEqual(saved["Categorized"]["categoryName"], "Pinned")
        self.assertEqual(saved[title]["categoryName"], "A/B%20")
        self.assertIsNone(saved["Uncategorized"]["categoryId"])
        self.assertTrue(saved["Uncategorized"]["pinned"])

    def test_import_single_markdown_and_reject_invalid_json(self):
        source = self.root / "Shell.md"
        self.add_text("Existing", "Shell")
        source.write_text("## Script\n```sh\n## Not a new item\n```\n\n## Another\nhi\n")
        self.assertEqual(self.snip("import", source), {"imported": 2, "skipped": 0})
        items = self.snip("snapshot")["items"]
        self.assertEqual({item["categoryName"] for item in items}, {"Shell"})
        self.assertEqual([(item["title"], item["body"]) for item in items],
                         [("Script", "```sh\n## Not a new item\n```"), ("Another", "hi"), ("Existing", "Existing")])
        broken = self.root / "invalid.json"
        broken.write_text('{"format":"snip","version":2,"categories":[],"items":[]}')
        self.assertIn("Expected a Snip JSON export", self.snip("import", broken, success=False))
        self.assertEqual(self.snip("snapshot")["items"], items)

    def test_numeric_new_tab_name_is_a_name_not_an_id(self):
        first = self.snip("create-category", "Alpha")["id"]
        self.write_history("numeric tab")
        ref = self.snip("snapshot")["inbox"][0]["ref"]
        created = self.snip("save-inbox-new", "--ref", ref, str(first))["categoryId"]
        self.assertNotEqual(created, first)
        snapshot = self.snip("snapshot")
        self.assertEqual({c["id"]: c["name"] for c in snapshot["categories"]}[created], str(first))
        self.assertEqual(snapshot["items"][0]["categoryId"], created)

    def test_subtitles_skip_the_title_and_describe_images(self):
        self.write_history("Heading\n\nSecond line", "one line only")
        inbox = self.snip("snapshot")["inbox"]
        self.assertEqual([entry["subtitle"] for entry in inbox], ["Second line", "1 line · 13 chars"])
        self.snip("pin-inbox", "--ref", inbox[0]["ref"])
        self.assertEqual(self.snip("snapshot")["items"][0]["subtitle"], "Second line")
        source = self.root / "pixel.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + (3).to_bytes(4, "big") + (2).to_bytes(4, "big"))
        self.history.write_text(json.dumps([{"type": "image", "path": str(source), "mime": "image/png"}]))
        self.assertEqual(self.snip("snapshot")["inbox"][0]["subtitle"], "PNG · 3×2 · 0 KB")
        source.unlink()
        self.assertEqual(self.snip("snapshot")["inbox"][0]["subtitle"], "PNG · file missing")

    def test_top_level_help_lists_only_public_commands(self):
        result = self.run_snip("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        public = {"add", "paste", "edit", "export", "import", "doctor", "config"}
        internal = ("snapshot", "pin-inbox", "save-inbox", "save-inbox-new", "toggle-pin", "delete",
                    "delete-category", "create-category", "used", "swap-order")
        listed = {line.split()[0] for line in result.stdout.partition("commands:\n")[2].splitlines()
                  if line.startswith("    ")}
        self.assertEqual(listed, public)
        for command in internal:
            self.assertNotIn(command, result.stdout)
        self.assertNotIn("==SUPPRESS==", result.stdout)
        self.assertEqual(self.run_snip("snapshot").returncode, 0)

    def test_default_cli_uses_public_plugin_id(self):
        self.executable("omarchy-shell", r'''printf '"%s %s %s %s"\n' "$1" "$2" "$3" "$4"''')
        self.assertEqual(self.snip(), "shell toggle themaxcoder.snip {}")


if __name__ == "__main__":
    unittest.main()
