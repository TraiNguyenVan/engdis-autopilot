# Handoff merge: upstream ED autopilot snapshot (Nov 2026)

Source: `ed_ai_handoff.zip`, a Windows-side snapshot of the same project that
scored the Advanced 2 midterm test at 100% where this repo's run stopped at 48%.
This branch ports that snapshot's *logic* into the repo; it does not copy the
snapshot wholesale and it does not run anything against a live course.

## What was merged

### `auto.py`

- **Test detection** (`IS_TEST_JS`): a selected step node named `Explorer`/`explore`
  is no longer treated as a test, and a step title matching `/explore|practice/`
  short-circuits before the `/test|review/` fallback. Previously the Explore step
  could be classified as a test, which is one way a "test" run produced a score
  from screens that were never real tests.
- **Counter/total fallbacks** (`st()`): when the pager DOM has no counter, read
  the `ed-la-taskspager` component (`tasksNodes.Children`, `SelectedNode.NodeId`,
  `Intro` at index 0) and then `navigationService._tasksList`. Without this, `st()`
  returned `counter=None`, so `is_last` was never true and the submit step was
  skipped.
- **`advance()` rewritten around real Angular navigation**: `tryGoPrevNext(1)`
  first, then a direct `ed-la-taskspager` `change.emit()` for the next child,
  then a wider set of button selectors. The old order clicked `.learning__taskNext`
  first and only fell back to Angular afterwards; on test pagers that button is
  detached and the advance silently did nothing.
- **Test intro auto-start**: a new block detects the selected test node at index 0
  and calls `onTaskClick(children[1])`, so a test that renders an intro node does
  not sit on "start" forever.
- **Question-widget wait before solving a test**: waits up to 8s for a real
  widget then computes `src` from `solver.source_text`. This is the guard against
  classifying an empty practice area as `other:` and walking the test unanswered.
- **Explore vs interactive**: an Explore screen that still contains interactive
  widgets (`.prMCQ__qaSet`, `.lessonMultipleAnswer`, `.dnditem`, `.wordBankTile`,
  ...) is no longer treated as a read-only Explore page, so the widgets get solved
  instead of being skipped.
- **Speaking**: a Send-to-Teacher button (`.openSpeech__SentTTBtn`,
  `.openSpeech__btnSend`, `[class*=SentTTBtn]`) is clicked first and reported as
  `speak: sent`.

### `solver.py`

- **LLM pool handling**: two passes over `LLM_MODELS`, 15s timeout, 4 attempts per
  model, explicit `HTTPError` handling that distinguishes daily-token exhaustion
  (`TPD` / `tokens per day` -> switch model immediately) from per-minute limiting
  (429 RPM -> back off 8s x attempt), plus an 8s pause between pool passes.
- **`ask_json`**: `json.loads(..., strict=False)` so verbatim newlines/tabs inside
  model output no longer discard an otherwise valid answer.
- **Media**: `transcribe_groq()` now accepts video as well as audio and sends the
  real filename/MIME; `transcript_for()` downloads the media over HTTP with a
  browser User-Agent instead of shelling out to `ffmpeg`, picks the extension from
  the URL (`.mp4`, `.m4a`, `.wav`, `.webm`, `.mp3`) and only uses the multimodal
  `input_audio` fallback for `.mp3`. This removes the ffmpeg dependency and makes
  listening/video tests transcribable in the container.
- **`play_media()`**: latches the `ended` event (`window._mediaEndedLatched`) and
  treats a `playing -> waiting` transition as "finished", instead of relying on
  `currentTime > 0 && paused`.
- **`set_step` / `set_next_step`**: navigationService is tried before the dropdown
  component, reading `SelectedIndex` from `_stepsList` first; the dropdown index
  is no longer assumed to be 1-based when falling back to
  `selectedListItemIndex`.
- **`solve_drag()`**: drops the `body.style.zoom = 0.8` workaround (which needed a
  reset afterwards and drifted coordinates), reads labels next to each drop zone
  (`prMT_T2T__answersText`, table headers) and includes them in the LLM prompt.

### `config.py` / `bootstrap_browser.py`

- `.env` lookup now also checks the module directory and its parent, so scripts
  started from a different working directory pick up the same file.

### `tools/scan_lesson_scores.py`

Read-only port of the handoff's score scanner, with the hardcoded
`d:\lab\...` paths replaced by `--course` / `--out` arguments. It never starts or
submits a test.

## Deliberate deviations from the handoff

1. **`.env` never overrides the real environment.** The handoff changed
   `_load_dotenv` to assign every key unconditionally. That would let a stale
   repo `.env` override `ED_COURSE` / `ED_UNIT` / `ED_PASSES` passed by
   `docker compose run -e ...` and by the supervisor, silently redirecting a run
   to the wrong course. Kept the original "set only if absent" contract; only the
   path search was added.
2. **No `setProgress()` forgery on the Send-to-Teacher path.** The handoff clicks
   the button and then calls `navigationService.setProgress(<next unfinished
   task>)`. That flips progress for a task the student may not have completed, so
   only the real button click is merged; the LMS records the submission itself
   (returns `speak: sent`).
3. **Browser profile default stays container-native.** The handoff defaulted
   `--profile` to `<repo>/data/profile`; the Docker harness mounts `/data/profile`.
   Default is now `ED_PROFILE` or `/data/profile`, which keeps container runs
   working and still allows an override for a bare-metal run.
4. **The `boost_all_tests_v3.py` booster was not merged.** It carries a hardcoded
   target list (course, unit, lesson, name) and retakes every one of them
   regardless of the recorded score, including when the score could not be read.
   Re-submitting a test replaces the stored score, so an unknown score can turn a
   recorded 100% into a lower one. Retakes stay behind the explicit
   `cover.py --test-only --min-score=... --lesson=...` path, which skips lessons
   already above the threshold.
5. **`scan_all_lesson_test_scores.py` / `list_sub100.py` were re-implemented, not
   copied.** The originals hardcode `d:\lab\...` import and output paths and write
   to `d:\lab\`.

## What was not verified

Nothing here was exercised against `ed22.engdis.com`. The 100% run happened on
the handoff author's machine and account. Verification for this branch is the
unit-test suite only; the first live run has to be a lesson whose current scores
are already recorded and known, so a regression is visible without risking an
unrecorded test.
