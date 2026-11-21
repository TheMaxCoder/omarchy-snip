# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-21

### Added

- Keyboard-first picker for Omarchy 4, with configurable shortcuts and search-first mode.
- Ranked fuzzy search across saved snippets and clipboard history.
- Clipboard, primary selection, and stdin capture; JSON and Markdown import/export.
- `snip doctor` checks for dependencies, config, clipboard history, database integrity, and a shortcut.

### Changed

- Clipboard actions use stable references and Omarchy's file paste helper.
- Saved images survive removal from clipboard history; existing databases migrate in place.
- Editor and terminal selection no longer depend on a specific terminal or editor.
