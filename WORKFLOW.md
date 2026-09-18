# Učna priprava workflow

Current operational details are in README.md.

User preferences: reMarkable Paper Pro; Google Calendar “Šolski testi”; Slovenian; GPT-5.6 Sol for reading after a visual handwriting comparison, GPT-5.6 Luna for generation and diagnostics. Local execution on this Mac with an installed hourly LaunchAgent.

The native app is installed at ~/Applications/Učna priprava.app. It uses study/desktop.py over stdio and stores private state under .private. Per-test inputs are total study hours, self-assessed knowledge, target grade, scope notes, a selectable tablet folder, image/PDF attachments, and an optional diagnostic pre-test. Objective scoring shows sampled weak topics and an initial time estimate; it does not predict a school grade. Generation obeys the selected minute budget and validates source references.

Folder selection: an explicit choice wins. Otherwise match the subject, then date/title-labelled test folders, then Test N by that subject’s calendar order in the September–August school year. If no test subfolders exist, use the entire subject folder recursively. Missing or ambiguous numbered folders need a manual choice. Automatic numbering can change when calendar dates change; explicit selection pins a folder ID.

The confirmed Slovenian test is 23 September 2026, 13:25–14:10. The captured authenticated timetable identified evaluation 21852686, “1. šolska naloga”, with scope “Tvorba neumetnostnega besedila”. Its existing calendar ID is preserved. Preparation starts 16 September. Never map that event to geography.

Verified: Google service-account event create/read/update/delete and refresh; reMarkable ingestion; all five geography notebooks (16 pages including four blank); Sol reading and Luna generation; three geography PDFs uploaded and downloaded with matching hashes; hourly scheduler installed and first run completed; native app compiled/opened; live 10-question diagnostic and a seven-day plan totaling 120 minutes; 46 offline tests.

Connection acceptance completed after renewed sign-in: a fresh headless session fetched ten weeks and discovered exactly two assessments. Slovenian: 23 September, 13:25–14:10; English: 7 October, 10:55–11:40, “1. pisno ocenjevanje”, scope grammar/vocabulary/reading comprehension. Both sync to Google Calendar. A duplicate caused by malformed text encoding was removed and the parser now normalizes that encoding; the original Slovenian UUID remains stable. The first school week starts on 1 September rather than the preceding August Monday. English has no matching reMarkable folder yet, so preparation asks for a folder or attachments. No further login is currently needed; normal session expiry may require future renewal.

Study packs are immutable versions, with separate notes, questions and answers. Source notebooks and handwritten responses are preserved. The scheduler requires the Mac to be available and online. API billing is separate from chat.

File explorer and multi-selection: per-test material_ids can contain notebooks and folders from multiple branches. Folders expand recursively at each run; overlaps are deduplicated, missing/deleted sources fail clearly, and generated output is excluded from source selection. Explicit selections survive date sync and are used for diagnostics, early preparation and scheduled runs. The live geography check verified two individual notebooks and a whole-folder overlap resolving to five unique notebooks.
