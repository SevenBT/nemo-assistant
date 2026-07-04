# Bundled Fonts

Drop font files into this directory and the app will scan and register them
automatically on startup (`.ttf` / `.otf` / `.ttc` are supported).

## Preferred: MiSans

Add any of the following (the file name does not matter; recognition is based
on the internal font family name `MiSans`):

- `MiSans-Regular.ttf`
- or the full set of MiSans weights

### Download

MiSans is open-sourced by Xiaomi and free for commercial use. Official download:
https://hyperos.mi.com/font/download/

After downloading, copy `MiSans-Regular.ttf` (and any weights you need, such as
Medium/Semibold) into this directory.

## Fallback

If this directory is empty or a font fails to load, the app falls back to the
system-installed `MiSans` → `Microsoft YaHei UI` → `Microsoft YaHei`
(see `app/ui/fonts.py`).
