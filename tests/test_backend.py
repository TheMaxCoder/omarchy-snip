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
            "XDG_CONFIG_HOME": str(self.root / "xdg-config"),
            "XDG_STATE_HOME": str(self.root / "xdg-state"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "OMARCHY_PATH": "",
            "VISUAL": "",
            "EDITOR": "",
        }
        self.write_history("clipboard value")

    def run_snip(self, *args):
        return subprocess.run(
            [SNIP, *map(str, args)], cwd=self.root, env=self.env, capture_output=True, text=True
        )

    def snip(self, *args, success=True):
        result = self.run_snip(*args)
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
            cursor = db.execute("INSERT INTO items(kind, title, path, content_hash) VALUES ('image', ?, ?, ?)",
                                ("Also used", str(owned), "fixture-hash"))
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
                             {"legacy_migrated": "2026-01-01", "schema_version": "2"})
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(self.snip("snapshot"), snapshot)

    def test_doctor_reports_requirements_and_nonfatal_warnings(self):
        self.paste_stub(bundled=True)
        self.executable("wl-paste", "exit 0")
        self.executable("xdg-terminal-exec", "exit 0")
        self.executable("hyprctl", r'''test "$*" = 'binds -j' && printf '%s' '[{"arg":"omarchy-shell shell toggle themaxcoder.snip {}"}]' ''')
        result = self.run_snip("doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for label in ("Python", "omarchy-clipboard-paste-file", "wl-copy", "wl-paste", "wtype",
                      "xdg-terminal-exec", "Clipboard history", "Config", "Database (schema 2)", "Hyprland binding"):
            self.assertIn(f"✓ {label}", result.stdout)

        self.history.write_text("not JSON")
        self.write_config({"unknown": True})
        (self.bin / "xdg-terminal-exec").unlink()
        self.executable("hyprctl", r'''printf '%s' '[{"arg":"themaxcoder.snip.old"}]' ''')
        result = self.run_snip("doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for message in ("✗ xdg-terminal-exec", "Enable omarchy.clipboard", "✗ Config warning",
                        'o.rebind("SUPER + CTRL + V", "Snip", { panel = "themaxcoder.snip" })'):
            self.assertIn(message, result.stdout)
        (self.bin / "hyprctl").unlink()
        self.assertNotIn("Hyprland binding", self.run_snip("doctor").stdout)

    def test_doctor_fails_without_requirements_or_on_broken_config_and_db(self):
        self.config.write_text("{")
        data_dir = Path(self.env["SNIP_DATA_DIR"])
        data_dir.mkdir()
        (data_dir / "snip.db").write_text("not a database")
        result = self.run_snip("doctor")
        self.assertNotEqual(result.returncode, 0)
        for label in ("omarchy-clipboard-paste-file", "wl-copy", "wl-paste", "wtype", "Config", "Database (schema 2)"):
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
        self.assertIn("wl-paste not found", self.snip("add", "Fail", success=False))
        self.executable("wl-paste", "printf 'line1\\nline2\\n' >&2; exit 17")
        self.assertEqual(self.snip("add", "Fail", success=False).splitlines(),
                         ["snip: Could not read text from the clipboard with wl-paste"])

    def test_default_cli_uses_public_plugin_id(self):
        self.executable("omarchy-shell", r'''printf '"%s %s %s %s"\n' "$1" "$2" "$3" "$4"''')
        self.assertEqual(self.snip(), "shell toggle themaxcoder.snip {}")


if __name__ == "__main__":
    unittest.main()
