# Phased Improvement Plan — trailcam_sorter

Status: **drafted 2026-06-12**, not yet started. Derived from the in-session code/UX
review (9 issues). This file is the source of truth for the roadmap; the session
buffer is not. Update the checkboxes as work lands.

## Approach

- Work phase by phase. Do **not** start a later phase until the prior one is
  committed and tests pass.
- Each behavioural change is TDD: write/extend a failing test in `tests/` first,
  then implement.
- Keep changes small and reviewable; one logical change per commit.

---

## Phase 1 — Safety & correctness (do first)

Goal: prevent data-loss / footgun scenarios and make the build identifiable.

- [x] **1.1 Output path validation.** Done — `check_dest_not_a_file()` + 3 tests;
  wired into CLI `main()` and GUI `_start` ahead of the dest-in-source guard.
- [x] **1.2 Dest-in-source guard.** Done — `check_dest_not_in_source()` + 4 tests
  (`tests/test_path_validation.py`); wired into CLI `main()` (exit 1) and GUI
  `_start` (blocking `messagebox.showerror`). Refuse (or warn + require confirm) when the
  resolved `dest_root` is the same as, or nested inside, the resolved `source`.
  Risk today: recursive scan picks up files the tool just copied, and copy-into-self.
  Use `Path` `is_relative_to` against both resolved paths. Apply in CLI `main()` and
  the GUI `_start`/run path so both entrypoints are covered.
- [x] **1.3 Sharpness fallback.** Done — found a real bug: with all-zero scores
  (cv2 unavailable) `max()` returned the *first list item*, not the deterministic
  base image. Gated the sharpness path on `is_cv2_available()`; added a
  monkeypatched test in `tests/test_sharpness.py`.
- [x] **1.4 `--version` flag.** Done — `__version__ = "1.1.1"` constant, `--version`
  argparse action (prints `trailcam_sorter.py 1.1.1`), and version in GUI title.
  Test asserts the constant matches semver.
- [x] **1.5 GUI clean shutdown (WM_DELETE_WINDOW).** Done — registered
  `WM_DELETE_WINDOW` → `_on_close`, which confirms + sets the cancel event before
  `destroy()` when a sort is running; Close button routed through the same handler.
  GUI behaviour needs a **manual** smoke (close mid-run) — not unit-testable headless.

- [x] **1.5b Honest cancel-during-inference message (follow-on).** Manual GUI test
  showed Cancel during inference *looks* like it does nothing (inference is atomic;
  cancel only lands at the post-inference checkpoint, line ~1006). `_on_cancel` now
  branches on `self._busy` to explain the batch can't be stopped midway and the bar
  keeps moving until it finishes. Animation intentionally left running (work IS
  still happening). Close button disabled-during-run confirmed intentional.

- [x] **1.5c High-visibility cancel cue (follow-on).** Log line was easy to miss.
  On cancel-during-inference the progress bar + status text now turn amber
  (`WARN_AMBER`) with a ⚠ message; reset to green/dim on next run. Manually verified.

Exit criteria: **MET** — all items done, `pytest` green (55 passed), CLI `--version`
verified, GUI X-close guard + amber cancel cue manually verified.

---

## Phase 2 — Run UX

Goal: make a run easier to understand and trust while it happens.

Items (from the review's UX bucket — to be expanded into concrete tasks when we
reach this phase):
- [ ] Clearer progress/status messaging during the long inference phase.
- [ ] Summary at end of run (counts, where files went, review folder size).
- [ ] Surface the dry-run preview results more visibly.
- [ ] Better error surfacing in the GUI (vs. only the log).

> Note: the per-item detail for Phases 2–4 was not captured verbatim in the
> session buffer. Re-review and flesh these out before starting Phase 2.

---

## Phase 3 — Options & persistence

Goal: remember user choices and make repeat runs cheap.

- [ ] Persist last-used options (output dir, confidence profile, toggles) in config.
- [ ] Checkpoint/resume polish (`--checkpoint-file` / `--resume-from-checkpoint`
  already exist — verify and document the UX).
- [ ] Report-CSV improvements.

---

## Phase 4 — Polish

Goal: cosmetic and documentation cleanup.

- [ ] README updates for any new flags (`--version`, validation behaviour).
- [ ] GUI layout / wording nits.
- [ ] Consider the deferred items in memory `project-state` (nearest-neighbour
  video matching is already shipped as `--video-match-mode nearest`; module split
  still deferred).

---

## Out of scope / deliberately deferred

- Module split (`trailcam_sorter.py` → `core/` + `ui/`) — deferred until contributors arrive.
- Feature roadmap (review UI, etc.) — tracked separately.
