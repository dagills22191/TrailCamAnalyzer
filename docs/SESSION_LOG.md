# Session Log

Newest first. Each entry cites its commits; `git log` is the full backstop.

## 2026-06-14 — Phase 4c, Advanced-mode removal + tooltips, v1.2.0 release

**Shipped v1.2.0:** https://github.com/dagills22191/TrailCamAnalyzer/releases/tag/v1.2.0

- **Phase 4c — path separator normalization** (`03fb250`). Added module-level `display_path(p)` (`os.path.normpath`, empty→empty). Source field (from filedialog, forward slashes) and Output field (config default, backslashes) now both render native separators. Applied at `src_var`/`out_var` init and in `_browse`. TDD: `tests/test_display_path.py` (3 tests). Closed out Phase 4.
- **Removed "Advanced mode" + added hover tooltips** (`3763c93`). Advanced mode only gated 3 toggles (2 on by default) — not worth the friction. Removed the gate; all 6 option toggles now show in two rows. Added a self-contained `_Tooltip` class (plain tkinter Toplevel, ~400ms delay, no new dependency, themed to INNER/TEXT/SEP) attached to all 6 checkboxes + Country/Region + Confidence slider via a local `tip()` helper. "(recommended)" moved off the EXIF label into its tooltip. Also folded in the **geofence/confidence hint truncation fix** (hint moved to its own full-width line). Dropped `advanced_mode` from `resolve_startup_settings` + persisted save; deleted `_set_advanced_mode`/`_on_advanced_mode_toggle`/`advanced_frame`; updated `tests/test_startup_settings.py`. Brainstormed first; spec at `docs/superpowers/specs/2026-06-14-remove-advanced-mode-tooltips-design.md` (gitignored).
- **Version bump + release** (`ecc357a`). `__version__` → 1.2.0; **also fixed installer `AppVersion` in setup.iss which had been stale at "1.0" through the entire 1.0.0→1.1.1 series.** Built via `build.ps1 -OneFile`, smoke-tested the windowed frozen exe by process-liveness (its `--version` prints nothing to console), zipped portable, pushed master + tag `v1.2.0`, `gh release create` with both assets (Setup.exe 207 MB, Portable.zip 304 MB). 82 tests green throughout.

**Process notes (now in project_setup memory):** version lives in TWO files (trailcam_sorter.py:47 + setup.iss); keep in sync. Frozen exe is windowed — smoke-test via Start-Process/HasExited, not stdout.
