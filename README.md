# CV Maker

A local web app that remembers your career and keeps your CV up to date for you.

Tell it something new in plain words, such as *"I got promoted to Senior Engineer
at Acme in March and led the move to Kubernetes, which cut costs 30%"*. Claude
files that into your **memory** and rewrites the **best version of your CV** from
everything it knows. You can edit the CV directly on the page and download it as
a PDF.

## How it works

```
 you type / attach a file
          │
          ▼
   ┌─────────────┐   Claude merges the new facts in (no duplicates, keeps ids,
   │   Memory    │   never invents), and asks follow-up questions that would
   │ memory.json │   strengthen the CV
   └─────────────┘
          │  (automatic after each update)
          ▼
   ┌─────────────┐   Claude picks, orders and polishes the strongest content,
   │     CV      │   tailored to your target role if you gave one
   └─────────────┘
          │
          ▼
   edit in place  →  Download PDF
```

- **Memory** is the source of truth. It keeps *everything*, including things
  that don't make it onto the current CV, so a later CV tailored to a different
  role can use them.
- **History and undo.** Every change is logged with what you typed and what
  changed, and the memory is snapshotted first so you can undo it.
- **Editing.** Click anywhere on the CV to change the wording; edits save
  automatically. Because a rebuild would overwrite them, the app won't
  auto-rebuild over manual edits. Click **Save edits to memory** and Claude
  folds your corrections and preferred wording back into memory, so future
  versions keep them.
- **Aim the CV.** Paste a job ad or describe a role and the CV is tailored to it.
- **Import.** Attach an existing CV (PDF or text) to fill the memory in one go.
- **Preferences.** Say things like *"always use UK spelling"* or *"keep it to
  one page"*. They're remembered and applied to every rebuild.
- **PDF.** **Download PDF** opens the print dialog with a print-ready layout;
  choose *Save as PDF*. The text in the PDF stays selectable, which
  applicant-tracking systems need. Pick A4 or US Letter in the toolbar.

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...     # from https://console.anthropic.com
python -m cv_maker                      # then open http://127.0.0.1:5000
```

Options:

| Flag / env var | Default | Meaning |
| --- | --- | --- |
| `--data` / `CV_MAKER_DATA` | `data/` | Where your memory and CV are stored |
| `--port` | `5000` | Port to serve on |
| `CV_MAKER_MODEL` | `claude-opus-5-5` | Claude model to use |

Without an API key the app still runs: you can edit the memory directly
(Memory → *Edit as JSON*) and get a plain CV built from it. Claude is needed
for plain-language updates and for the polished, tailored CV.

## Your data

Everything is stored as plain files in the data directory:

| File | Contents |
| --- | --- |
| `memory.json` | Everything known about you |
| `history.jsonl` | Log of every update |
| `snapshots/` | Memory before each change (for undo) |
| `cv.json`, `cv.html` | The current CV, including manual edits |
| `settings.json` | Target role, auto-rebuild, and page size |

`data/` is in `.gitignore` so personal details aren't committed by accident.
Back it up, or point `--data` at a private folder or repository.

Your memory and any files you attach are sent to the Claude API when you add
something or rebuild the CV.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

| Path | Role |
| --- | --- |
| `cv_maker/schema.py` | Memory and CV data models (also the structured-output schemas) |
| `cv_maker/store.py` | File storage, history, snapshots and undo |
| `cv_maker/ai.py` | Claude prompts for updating memory and writing the CV |
| `cv_maker/render.py`, `templates/cv.html.j2` | CV HTML, plus the no-AI fallback layout |
| `cv_maker/app.py` | Flask routes |
| `cv_maker/static/` | Browser UI (`cv.css` is the CV's look, for both screen and print) |

To change how the CV looks, edit `cv_maker/static/cv.css`. To change what makes
a "best" CV, edit `CV_SYSTEM` in `cv_maker/ai.py`.
