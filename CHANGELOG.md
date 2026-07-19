# Changelog

All notable changes to this project will be documented in this file.

This project follows a lightweight changelog format inspired by Keep a Changelog, and uses semantic versioning once stable releases begin.

## [Unreleased]

## [0.2.0] - 2026-07-19

### Changed

- Improved chat interaction reliability and safety.
- Optimized chat rendering updates.
- Added automated Windows Draft Release packaging.
- Added release metadata and version consistency validation.

### Fixed

- Fixed issues affecting chat interaction behavior.

## [0.1.0] - 2026-07-04

First public release: floating desktop AI assistant with selection actions,
screenshot OCR, Markdown notes and stickies, a tool-calling agent, and
observable agent runs. Windows only.

### Added

- Security policy for responsible vulnerability reporting.
- Public development notes for frameless window, selection capture, theme, and dialog implementation trade-offs.
- Dependency license notes for source and binary release preparation.
- Dependabot configuration for Python dependencies and GitHub Actions.
- uv lock workflow for reproducible development and CI installs.
- Release checklist covering source, Windows binary, and dependency license review.
- Repository consistency checks for metadata, Markdown links, stale placeholders, and PyInstaller hidden imports.

### Changed

- Aligned public documentation with the `SevenBT/nemo-assistant` repository URL.
- Renamed the PyInstaller spec and packaged executable branding to Nemo Assistant.
- Replaced placeholder-style default model templates with conservative starter examples.
- Documented web search provider configuration.

### Fixed

- Corrected the show/hide shortcut in English and Chinese README files.
- Added the missing `pytest-cov` development dependency used by the contribution guide.
- Replaced references to an untracked screenshot AI TODO document with public documentation.
