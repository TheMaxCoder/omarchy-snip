import json
import os
from pathlib import Path
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
            "VISUAL": "",
            "EDITOR": "",
        }
        self.write_history("clipboard value")

    def snip(self, *args, success=True):
        result = subprocess.run(
            [SNIP, *map(str, args)], cwd=self.root, env=self.env, capture_output=True, text=True
        )
        if not success:
            self.assertNotEqual(result.returncode, 0)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_history(self, *texts):
        self.history.write_text(json.dumps([{"type": "text", "text": text} for text in texts]))

    def write_config(self, value):
        self.config.write_text(json.dumps(value))

    def executable(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + script + "\n")
        path.chmod(0o700)
        return path

    def test_library_workflow(self):
        fresh = self.snip("snapshot")
        self.assertEqual(fresh["categories"], [])
        self.assertEqual(fresh["items"], [])
        category = self.snip("create-category", "Prompts")["id"]
        self.write_history("alpha body", "beta body")
        self.snip("save-inbox", 0, category)
        self.snip("save-inbox", 1, category)
        self.write_history("clipboard value")

        snapshot = self.snip("snapshot")
        self.assertEqual(snapshot["categories"][0]["name"], "Prompts")
        self.assertEqual(len(snapshot["items"]), 2)
        self.assertEqual(len(snapshot["inbox"]), 1)
        self.assertEqual(snapshot["clipboardFile"], str(self.history))

        self.snip("pin-inbox", 0)
        snapshot = self.snip("snapshot")
        self.assertEqual(len(snapshot["items"]), 3)
        pinned = [item for item in snapshot["items"] if item["pinned"]]
        self.assertEqual(len(pinned), 1)

        self.snip("toggle-pin", pinned[0]["id"])
        snapshot = self.snip("snapshot")
        self.assertEqual(len(snapshot["items"]), 2)
        self.assertFalse(any(item["pinned"] for item in snapshot["items"]))

        self.snip("save-inbox", 0, category)
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

        self.snip("save-inbox-new", 0, "Scratch")
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
                     "copy": ["Key_C"], "back": ["NoSuchQtKey"], "close": ["Ctrl+"], "noAction": []},
        })
        config = self.snip("config")
        self.assertEqual({key: config[key] for key in DEFAULTS}, DEFAULTS)
        for option in ("extra", "startInSearch", "terminal", "editor", "keys.up", "keys.down",
                       "keys.paste", "keys.copy", "keys.back", "keys.close", "noAction"):
            self.assertTrue(any(option in warning for warning in config["warnings"]), option)

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
        item_id = self.snip("pin-inbox", 0)["id"]
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

    def test_default_cli_uses_public_plugin_id(self):
        self.executable("omarchy-shell", r'''printf '"%s %s %s %s"\n' "$1" "$2" "$3" "$4"''')
        self.assertEqual(self.snip(), "shell toggle themaxcoder.snip {}")


if __name__ == "__main__":
    unittest.main()
