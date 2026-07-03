# Dependency License Notes

Nemo Assistant's own source code is released under the MIT License. Third-party dependencies keep their own licenses.

This file is not legal advice. It is a maintainer checklist for source releases and packaged binary releases.

## Direct Runtime Dependencies

The following license values were read from installed package metadata during the open-source readiness pass:

| Package | License metadata |
| --- | --- |
| PyQt6 | GPL-3.0-only |
| pyqt6-fluent-widgets | GPLv3 |
| openai | Apache-2.0 |
| APScheduler | MIT |
| httpx | BSD-3-Clause |
| beautifulsoup4 | MIT License |
| pyperclip | BSD |
| rapidocr-onnxruntime | Apache-2.0 |
| numpy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| keyring | MIT |
| keyboard | MIT |
| mouse | MIT |
| uiautomation | Apache 2.0 |
| pywin32 | PSF |
| PyPDF2 | BSD License |
| Markdown | BSD-3-Clause |
| Pygments | BSD-2-Clause |
| html2text | GPL-3.0-or-later |
| litellm | MIT |

## Binary Release Checklist

Before distributing a PyInstaller build:

- Review the licenses of all bundled transitive dependencies, not only direct dependencies.
- Include required license texts and notices next to the binary or in the release archive.
- Review GPL/commercial licensing obligations for Qt/PyQt and related GUI packages.
- Regenerate this inventory from the exact release environment.

Suggested command after installing a license inventory tool:

```bash
pip install pip-licenses
pip-licenses --with-license-file --format=markdown > build/dependency-licenses-full.md
```

## Adapted Source Code

Code ported or adapted from third-party projects is documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
