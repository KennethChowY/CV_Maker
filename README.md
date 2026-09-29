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
- **Fixing wrong information.** In the **Memory** tab, click **Edit** on any
  entry to correct it in a form, move it between Experience and Projects, or
  change a publication's type. **+ Add** creates a new entry. These edits don't
  rebuild the CV each time; click **Rebuild CV** when you're done.
- **Section order.** In the **Sections** box, drag sections into the order you
  want (or use the arrows), and untick any you want to hide. The order is kept
  for every future rebuild.
- **Gaps.** Unfilled placeholders like `[rating]` are highlighted on the CV and
  listed under *Tips*, so nothing half-finished gets sent by accident.
- **Design.** Above the CV, pick a template (**Classic**: serif with a centred
  header, the style most tech recruiters know; **Modern**: sans-serif with a
  colour accent; **Minimal**: black and white), the paper size, and **Fit to one
  page**, which shrinks text and spacing just enough to fit. Dashed lines in the
  preview show where each new page would start.
- **CV check.** Updates as you edit: page count, unfilled gaps, bullets with no
  numbers, weak openings like "Responsible for…", overlong bullets, mixed UK/US
  spelling, present tense on past roles, mixed date formats, inconsistent full
  stops, repeated words, missing contact details, and, if there's a job ad,
  which of its keywords your CV is missing. Click a quoted bullet to jump to it.
  Misspellings are underlined in red by your browser as you edit.
- **Improve one bullet.** Click a bullet on the CV for **Stronger**, **Add a
  number**, **Shorter**, **Match job ad** or **Ask…** (your own instruction).
  You get three versions; click one to use it. *Add a number* only uses numbers
  from your memory and otherwise leaves a gap like `[X%]` for you to fill in.
- **Applications.** In the **Applications** tab, add a job (company, role, the
  job ad) to get a CV tailored to it, without changing your general CV. Track
  each one's status (Draft, Applied, Interview, Offer…), the date applied and
  notes. Switch between CVs with the menu above the CV. Once an application is
  past *Draft*, its CV is kept as sent.
- **Cover letters.** The **Cover letter** tab writes a letter for the open CV
  from your memory and that job's ad (Professional, Warm or Concise). Edit it on
  the page; each application keeps its own.
- **Aim the CV.** Paste a job ad or describe a role and the CV is tailored to it.
- **Import.** Attach an existing CV (PDF or text) to fill the memory in one go.
- **Preferences.** Say things like *"always use UK spelling"* or *"keep it to
  one page"*. They're remembered and applied to every rebuild.
- **Downloads.** **Download PDF** saves a PDF straight away, made by the Chrome,
  Edge or Brave browser already on your computer: selectable text (which
  applicant-tracking systems need), your template, no browser header or footer.
  If none of those browsers is installed, the print dialog opens instead;
  choose *Save as PDF*. **Word** downloads a .docx for portals that ask for one.
  Both work for the CV and the cover letter.

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
  model too big for your computer's memory gets very slow. The app keeps the
  model loaded between updates, and a rebuild only rewrites entries that
  changed, so most rebuilds after the first are much quicker.
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

Choose **Claude** in the AI model box and paste an API key from
https://console.anthropic.com/settings/keys. The key is checked with Anthropic,
then saved only in `data/secrets.json` on your computer (readable only by you),
and never shown on the page again. **Remove key** deletes it. You can switch
between Claude and a free local model at any time; your memory and CVs carry
over. Setting `ANTHROPIC_API_KEY` in the terminal also works.

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
| `cv.json`, `cv.html`, `letter.json` | The general CV (including manual edits) and its cover letter |
| `versions/<id>/` | One folder per job application: its details, tailored CV and cover letter |
| `settings.json` | Chosen model, design, section order and other settings |
| `secrets.json` | Your Claude API key, if you added one on the page |
| `wording_cache.json` | Local model's wording, reused so unchanged entries aren't rewritten |

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
| `cv_maker/writing.py` | Prompts shared by both backends: bullet rewrites and cover letters |
| `cv_maker/export.py` | PDF (via a local Chrome-based browser) and Word downloads |
| `cv_maker/ollama.py` | Local-model backend (Ollama) and the change-merging logic |
| `cv_maker/models.py` | The AI model picker: choosing, downloading and switching models |
| `cv_maker/render.py`, `templates/cv.html.j2` | CV HTML, plus the no-AI fallback layout |
| `cv_maker/app.py` | Flask routes |
| `cv_maker/static/` | Browser UI: `app.js` (main), `assist.js` (bullet help, cover letter), `cv.css` (the CV's look on screen and in print) |

To change how the CV looks, edit `cv_maker/static/cv.css`. To change what makes
a "best" CV, edit `CV_SYSTEM` in `cv_maker/ai.py`.
