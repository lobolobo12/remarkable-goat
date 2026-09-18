# reMarkable Study

Slovenian study notes, practice tests, separate solutions and a seven-day study plan made from your own reMarkable Paper Pro folders.

## Connection status

- reMarkable: paired; notebook download and handwritten PDF rendering are verified for Biologija and all five Geografija notebooks.
- Google Calendar: the dedicated service account is connected to **Šolski testi** only. Live create/read/update/delete and fresh-token checks passed. No domain or weekly Google OAuth reauthorization is required.
- OpenAI: the saved key has verified access to **GPT-5.6 Luna**, selected for study-pack generation. **GPT-5.6 Sol** is selected for handwriting reading after a visual comparison on the long Rastje page: Luna omitted kserofite and misread kambisoli, while Sol preserved both. This is a one-page comparison, not a general model benchmark. `reading_model` controls extraction independently; results are cached until notes or the reader change.
- eAsistent: connected and verified after renewed sign-in. A fresh headless browser reused the saved session and fetched ten weeks, discovering Slovenian on 23 September and English on 7 October. Teacher-provided title/scope and Slovenian text encoding are verified. Both events were synchronized to Google Calendar; the original Slovenian event ID was preserved. English still needs a notes folder or attachments.
- Tablet delivery: all three geography PDFs were uploaded and downloaded again; their bytes matched the local originals.
- Scheduler: installed and enabled as an hourly LaunchAgent. Its first run synchronized the confirmed Slovenian test and correctly waited until 16 September to prepare it.

## Mac app

Open **~/Applications/Učna priprava.app**. This is a native SwiftUI app with a private JSON-over-stdio Python bridge; no local web server, web hosting or extra account is needed. Keep this workspace and its `.venv` in place, because the app uses them.

**Datoteke reMarkable** opens the file explorer: expandable folder tree, folder contents, search across filenames, parent-folder navigation, and cached PDF previews. **Osveži** refreshes only the library listing. Generated study outputs remain visible but cannot be selected as source folders. From a test, use **Izberi zapiske in mape**. Tick multiple notebooks or folders across the library, or open a folder and choose **Izberi celo mapo**. **Uporabi izbor** applies the selection to the form; **Shrani nastavitve** saves it. Selected folders include all nested notebooks and future additions; overlaps are deduplicated. An explicit selection replaces automatic folder matching for that test and is used by both the diagnostic and study generation. **Ponastavi na samodejno izbiro Test N** restores automatic matching.

The app shows a monthly calendar and all saved tests. For each test you can set total study hours, confidence (0–4), target grade (2–5), and the topics on the test. Choose any reMarkable folder or keep automatic Test N matching. Add PDF, PNG, JPG, WebP or TIFF attachments (20 MB each); they become source pages alongside your tablet notes. Save preferences with **Shrani nastavitve**. **Pripravi zapiske in vaje** saves first and can prepare early.

**Ustvari predtest** creates 6–12 source-cited multiple-choice questions (the live geography check produced 10). Answer each question or select **Ne vem**, then choose **Oceni predtest**. Scoring is deterministic against the generated key. It shows weak topics and a transparent initial study-time estimate: 15 minutes of review per sampled topic plus 25 minutes per weak topic, scaled by target grade and rounded up to 15 minutes. This is a planning heuristic, not a calibrated grade prediction. **Uporabi ta čas** is optional. Your chosen budget, confidence, target and diagnostic results shape the next pack; daily minutes must add up to your total budget. A live 120-minute, seven-day plan passed validation.

**Poveži eAsistent** opens its official login. **Osveži povezave** imports dates, synchronizes Calendar, refreshes tablet folders and checks due preparation. The app shows attention messages when a connection needs work. Closing the app leaves the hourly worker installed.

To rebuild: `.venv/bin/python macos/build.py`. The reviewable source is `macos/StudyApp.swift`; the resulting app is in `dist/`.

## Normal operation

The hourly worker reads eAsistent timetable assessment markers from the start of the current school year through the next nine weeks, matches subject folders, synchronizes test dates and lesson times to Šolski testi, and generates material when a test is within seven days. It checks again at login and catches up after the Mac wakes. The Mac must be available; it cannot run while powered off.

Notebook content is sent to the OpenAI API, including handwriting and diagrams. Source references are validated and uncertain handwriting is flagged. Model output cannot guarantee a perfect transcription or predict the real test.

The PDFs appear locally under `output/TEST_ID/VERSION/` and, when tablet delivery is enabled, on reMarkable under:

```text
Učna priprava/
  2026-09-23 - Slovenščina - <test identifier>/
    Različica <version>/
      Urejeni zapiski
      Preizkus za vajo
      Rešitve in točkovnik
```

Source notebooks are never modified. New versions are separate documents, preserving your handwritten answers in older practice tests. Answer keys stay separate from exercises. `output/index.html` provides local links and run status.

## Source folders

A unique subject folder such as `Slovenščina` or `Geografija` is matched automatically, including subject abbreviations like SLO and GEO. With no test subfolders, its complete contents are used recursively.

To select only one test's material automatically, use a date-labelled folder:

```text
Geografija/
  Test 2026-10-15/
    Podnebje
    Vaje
```

Folders named `Test 1`, `Test 2`, etc. map automatically to tests of the same subject in calendar order, within the school year starting in September. Past tests in that year count; cancelled tests do not. Adding or moving a test can change automatic numbering, so choose a folder explicitly when you want the assignment pinned. Date/title matches take priority over numbered folders; a manual choice always wins. If numbered subfolders exist but the required number is missing or duplicated, preparation asks for a mapping.

Manual mapping is also available in the CLI:

```sh
.venv/bin/study list-tests
.venv/bin/study folders
.venv/bin/study map-test --id TEST_UUID --folder FOLDER_UUID
```

Subject aliases or unusually named folders can be mapped with `map-folder --subject Matematika --folder FOLDER_UUID`. Missing/ambiguous folders still allow calendar dates to synchronize, but study preparation reports that a folder mapping is needed.

## Connect and run

```sh
uv sync --extra cloud
.venv/bin/python -m playwright install chromium
.venv/bin/study doctor
.venv/bin/study connect-easistent
```

`connect-easistent` opens a dedicated browser on the official eAsistent website. Sign in there and open **Urnik**. Only this workflow's browser session is saved in `.private/`; the program does not extract Safari passwords or cookies. The earlier mobile API login form was retired after eAsistent rejected that authentication method. If the official session expires, run `connect-easistent` again.

```sh
.venv/bin/study sync-dates
.venv/bin/study run
.venv/bin/study prepare-test TEST_UUID   # one-time early preparation check
.venv/bin/study install-scheduler
.venv/bin/study scheduler-status
```

The scheduler is a macOS LaunchAgent, `si.remarkable.study`, which runs hourly and at login. Its logs are `.private/scheduler.log` and `.private/scheduler-error.log`; `.private/last-run.json` contains the latest result. Overlapping runs are prevented by a file lock.

Manual dates remain supported through `add-test --subject ... --title ... --date YYYY-MM-DD --folder FOLDER_UUID`. `cancel-test TEST_UUID` marks an explicit cancellation. Missing source records never cancel tests automatically. `watch` remains available as a foreground daily worker.

## Google Calendar

Active service account: `remarkable-study-calendar@stoked-proxy-499122-j8.iam.gserviceaccount.com`. It has no Cloud project roles or domain-wide delegation. Only **Šolski testi** is shared with permission to change events and see their details; it cannot manage sharing.

The private key is `.private/google-service-account.json` with owner-only permissions. `connect-google-service-account` verifies read access before selecting it. The active implementation requests `calendar.events`; calendar sharing defines the resource boundary. Stable event IDs prevent duplicates when dates change or requests are retried. Events have seven-day popup reminders and no guests.

The optional `connect-google` command switches back to user OAuth (`calendar.app.created`) and uses the older `.private/google-client.json` and `.private/google-token.json`. The project's OAuth Testing limitation applies only to that optional connection, not the active service account.

## Reliability and limits

- Failed or inaccessible timetable responses preserve previous records and report a reconnect/fetch error. Preparation based on eAsistent is paused until fresh dates are available.
- Changed dates or notes produce a new study-pack version. Unchanged work is cached. Completed AI generation is cached separately so a PDF rendering retry need not pay again.
- Defaults are 100 source pages per test and two newly generated packs per run. These are workload limits, not a monetary budget. OpenAI API billing is separate from this chat.
- Ambiguous tablet upload results are checked against the destination before retrying; uncertain missing results stop rather than blindly create duplicates.
- eAsistent is an unofficial read-only integration of the normal timetable view. Site changes or account-package restrictions can interrupt it. No access restriction is bypassed.

## Development checks

```sh
.venv/bin/pytest -q
.venv/bin/ruff check study tests
```

46 tests cover personal settings, diagnostic scoring, attachment conversion, subject-specific numbering, source isolation, the seven-day trigger, timetable validation, reschedules, missing data, folder ambiguity, calendar retries, upload recovery and versioned publication. Unit tests use fixtures and make no paid API calls.

References: [OpenAI PDF inputs](https://developers.openai.com/api/docs/guides/file-inputs), [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [remarkapy](https://github.com/j6k4m8/remarkapy), [remarks](https://github.com/avncharlie/remarks), [eAsistent timetable format reference](https://github.com/LovroG05/goeasistent).
