# English Discoveries HTTP API findings (Track B)

Measured on 2026-11-06 against `ed22.engdis.com/ptithcm`, course
`Advanced 2` (`CourseId 45689`), headless Chromium over CDP 9225.
Everything below was observed live, not inferred from docs.

## Auth

- API host: `https://edwebservices2.engdis.com/api/` (from `localStorage.api.host`).
- Bearer token: `JSON.parse(localStorage.Student).Token` (245 chars, JWT).
- The token the browser sends is byte-identical to the one in `localStorage.Student`
  (verified against the app's own `SetProgressPerTask` request headers).
- **Cookie auth does not work cross-origin.** `PreflightWildcardOriginNotAllowed`
  (`net::ERR_FAILED`): the preflight answers `204` with `Access-Control-Allow-Origin: *`,
  which browsers reject for credentialed requests. Any API client must use the Bearer
  header and omit credentials.
- `https://ed22.engdis.com/WebApi/...` (same-origin) does **not** serve the API —
  it answers `200` with the SPA error page HTML.

## Endpoints seen in the bundles (`learningAreaApp.js`, `LAScripts.min.js`)

Read:
- `CourseTree/GetUserNodeProgress/<courseId>` — POST, tree read.
- `CourseTree/GetCourseProgress/`, `CourseTree/GetStaticCourseTree/`, `CourseTree/GetLessonInDummyCourse/`
- `practiceManager/GetItem/<NodeId>/<itemCode>/<n>/<n>/<n>/` — GET per practice item
  (e.g. `practiceManager/GetItem/35614/a2sdttp02/25/0/7/`, `200`).
- `practiceManager/GetItemPreview/`

Write:
- `Progress/SetProgressPerTask` — POST `{CourseId, ItemId}`. Fires the **first time a
  learner touches an item** (clicking any answer label is enough). Body carries no
  answer text, no correctness, no score — only the item id.
- `Progress/SetUserCourseUnitComponentProgress/<nodeId>/<n>/<n>`
- `Progress/SetUserCourseProgress`, `Progress/SaveUserMarks`, `Progress/Course/100`
- `Ping/KeepAlive`, `Ping/Ping?lessonSessionId=`
- `Progress/SetTimeOnLesson/`

## Gate results

| Gate | Question | Result |
|---|---|---|
| G1 | Does an answer-bearing request leave the page for practice items? | **No.** Only `{CourseId, ItemId}`. Correctness is evaluated client-side; the server never sees the chosen answer for practice. |
| G2 | Is the score visible in a response? | Not captured. Graded test scoring happens on submit through the legacy jQuery `LAScripts` player (`submitTest`), which is a submit of a graded test — not exercised. |
| G3 | Is there a separate progress POST? | **Yes**, `Progress/SetProgressPerTask`, one call per item, idempotent-looking. |

## Read-back is unresolved

`POST CourseTree/GetUserNodeProgress/45689` with `[{ParticleId:45689, NodeType:1,
LockedNodes:null, particleHasProgress:true, lowestNodeType:6}]` returns `200` and the
correct tree (unit/lesson/step/task names, ids), but **every `Progress` is `0`** and
`IsDone` is `false`, while the UI simultaneously shows Unit 1 at 100%.

Tried and still zeros/empty: `StudentID` and `InstitutionId` headers; `LockedNodes: []`;
`NodeType` 2/3/4/9 with `ParticleId` unit/lesson; `lowestNodeType` 5 and 6;
same-origin `/WebApi/...`. Only (course, `NodeType 1`) answers at all.

Consequence: an API client can *write* per-item progress but cannot *read* real progress
back, so it cannot confirm its own effect without loading the UI.

## Verdict: NO-GO for replacing UI automation

- The automation's expensive part (reading the task, choosing answers, dragging, typing)
  cannot move to the API: the server never receives the answers.
- The only replayable call, `SetProgressPerTask`, marks an item done without doing it and
  without any way to verify the result — that is completion forging, not acceleration.
- Keep the UI driver. `api_spike.py` stays as the reference client:
  - `python3 api_spike.py tree` — dump course tree (names/ids/progress)
  - `python3 api_spike.py read 45689` — single node read
  - `python3 api_spike.py replay <LessonName>` — list task ids of a lesson (no writes)
  - `python3 api_spike.py write <ItemId>` — one `SetProgressPerTask` call, **refused**
    unless the owning lesson is already ≥99.9%, so it can only confirm the path.

## Instrumentation added

- `netcap_hook.js` — XHR/fetch/WebSocket recorder (method, url, headers, bodies,
  status, error/abort/timeout).
- `netcap.py` — installs the hook, drives one task cycle, writes `net_calls.json`.
- `netreport.py` — groups captured calls into an endpoint map.
- `driver.Tab.events` — CDP `Network.*` trace with real status codes and
  `Network.loadingFailed.errorText` (this is what produced the CORS diagnosis;
  the JS hook alone reports those failures as `status 0`).
