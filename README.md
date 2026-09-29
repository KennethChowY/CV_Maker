# CV Maker

A local web app that remembers your career and keeps your CV up to date for you.

Tell it something new in plain words, such as *"I got promoted to Senior Engineer
at Acme in March and led the move to Kubernetes, which cut costs 30%"*. An AI
model files that into your **memory** and rewrites the **best version of your CV**
from everything it knows. You can edit the CV directly on the page and download
it as a PDF.

It can use either:

- **A free local model** through [Ollama](https://ollama.com). It runs on your
  own computer, costs nothing, and your data never leaves your machine. This is
  the default when no Claude API key is set.
- **Claude** through the Anthropic API. It's pay-as-you-go (a few cents per
  update) and writes noticeably better CVs, especially on modest hardware.

## How it works

```
 you type / attach a file
          │
          ▼
   ┌─────────────┐   The AI merges the new facts in (no duplicates, keeps ids,
   │   Memory    │   never invents), and asks follow-up questions that would
   │ memory.json │   strengthen the CV
   └─────────────┘
          │  (automatic after each update)
          ▼
   ┌─────────────┐   The AI picks, orders and polishes the strongest content,
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
  auto-rebuild over manual edits. Click **Save edits to memory** and the AI
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

Requires Python 3.10+. Install the app's packages into a virtual environment
(a private folder of packages just for this project):

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Each time you open a new terminal, run `source .venv/bin/activate` again
before starting the app. Your prompt shows `(.venv)` when it's active.

### Option A: free local model (Ollama)

1. Install Ollama from https://ollama.com/download and open it.
2. Start the app:
   ```bash
   python -m cv_maker        # then open http://127.0.0.1:5000
   ```
3. In the **AI model** box at the top left, pick a model. If it isn't
   downloaded yet, click **Download**; the app switches to it when the download
   finishes. Your choice is remembered.

| Model | Download | Notes |
| --- | --- | --- |
| `qwen3:4b` | ~2.5 GB | Fast and good. Best for most laptops. |
| `llama3.2` | ~2 GB | Fastest, simpler writing. |
| `qwen3:8b` | ~5.2 GB | Best free writing. Needs a computer with 16 GB of memory. |

Any other model you've downloaded with Ollama also appears in the list.

What to expect:

- **Speed.** Local models run much faster on Apple Silicon (M1 or later) or a
  computer with a graphics card. If a model is slow, pick a smaller one; a
  model too big for your computer's memory gets very slow.
- **Quality.** Local models write weaker CVs than Claude. So with a local model
  the app lays out the CV itself (newest first, consistent formatting) and the
  model only improves the wording. Check the result, and fix wording directly
  on the CV.
- **Safety of your memory.** With a local model, the model only reports what
  changed and the app merges it, so an update can't accidentally wipe existing
  entries.
- **PDFs.** Attached PDFs are converted to text first, so scanned (image-only)
  PDFs won't work; paste the text instead.

### Option B: Claude (paid, best quality)

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # from https://console.anthropic.com
python -m cv_maker
```

With the key set, **Claude** becomes available in the AI model box. You can
switch between Claude and a free local model there at any time; your memory
and CV carry over.

`--ai` sets the starting choice before anything has been picked on the page:

```bash
python -m cv_maker --ai ollama    # start with the local model
python -m cv_maker --ai claude    # start with Claude
python -m cv_maker --ai none      # start with no AI: plain layout, edit memory by hand
```

### Options

| Flag / env var | Default | Meaning |
| --- | --- | --- |
| `--ai` / `CV_MAKER_AI` | `auto` | Starting choice: `auto`, `claude`, `ollama` or `none` |
| `--data` / `CV_MAKER_DATA` | `data/` | Where your memory and CV are stored |
| `--port` | `5000` | Port to serve on |
| `CV_MAKER_OLLAMA_MODEL` | `qwen3:8b` | Starting local model, before one is picked on the page |
| `CV_MAKER_OLLAMA_CONTEXT` | `16384` | Local model context size; raise it if you see "ran out of room" |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Where Ollama is running |
| `CV_MAKER_MODEL` | `claude-opus-5-5` | Claude model to use |

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

With the local model, nothing leaves your computer. With Claude, your memory
and any files you attach are sent to the Claude API when you add something or
rebuild the CV.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

| Path | Role |
| --- | --- |
| `cv_maker/schema.py` | Memory and CV data models (also the structured-output schemas) |
| `cv_maker/store.py` | File storage, history, snapshots and undo |
| `cv_maker/ai.py` | Claude backend and the CV-writing prompt |
| `cv_maker/ollama.py` | Local-model backend (Ollama) and the change-merging logic |
| `cv_maker/models.py` | The AI model picker: choosing, downloading and switching models |
| `cv_maker/render.py`, `templates/cv.html.j2` | CV HTML, plus the no-AI fallback layout |
| `cv_maker/app.py` | Flask routes |
| `cv_maker/static/` | Browser UI (`cv.css` is the CV's look, for both screen and print) |

To change how the CV looks, edit `cv_maker/static/cv.css`. To change what makes
a "best" CV, edit `CV_SYSTEM` in `cv_maker/ai.py`.
