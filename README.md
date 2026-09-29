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
  the default when no API key is set.
- **Your own API key** from an AI service: OpenAI, Anthropic, Google Gemini,
  Groq, OpenRouter, xAI or any OpenAI-compatible service. It's pay-as-you-go
  with that service (typically a few cents per update) and writes noticeably
  better CVs than small local models, especially on modest hardware.

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
- **Undo my edits.** If hand edits to a CV go wrong, **Undo my edits** returns
  it to the last generated version.
- **Backup.** **Back up** in the Memory tab downloads everything (memory, CVs,
  applications, letters; never your API key) as a zip. To restore, unzip it and
  use its `data` folder as the app's data folder. **Automatic backups** saves
  one to a folder you choose (iCloud Drive is suggested on a Mac), at most once
  an hour after you change something, keeping the latest 30.
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
- **Tidy lines and page breaks.** When a bullet spills a single word onto an
  extra line, the letter spacing is tightened invisibly to pull it back (in the
  preview and the PDF alike); longer spill-overs are listed in the CV check.
  Pages break at sensible places: never straight after a heading, never in the
  middle of a short entry or a list section like Skills, never leaving one bullet
  alone at the top of a page, and a long entry keeps its title with its first
  two bullets. Pages 2 onwards start with a small running header (your name and
  "Page 2 of 2"), and when a job continues from the previous page it's
  introduced with "Job title · Organisation (continued)". The dashed line in
  the preview shows exactly where the next page starts, and the check warns if
  the last page is nearly empty.
- **CV check.** Updates as you edit: page count, unfilled gaps, bullets with no
  numbers, weak openings like "Responsible for…", overlong bullets, mixed UK/US
  spelling, present tense on past roles, mixed date formats, inconsistent full
  stops, repeated words, missing contact details, and, if there's a job ad,
  which of its keywords your CV is missing (click one to add it to your memory,
  if it's true for you). Click a quoted bullet to jump to it.
  Misspellings are underlined in red by your browser as you edit.
- **Improve one bullet.** Click a bullet on the CV, then the ✨ beside it, for
  **Stronger**, **Add a number**, **Shorter**, **Match job ad** or **Ask…** (your own instruction).
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
- **Import.** Attach an existing CV (PDF, Word or text), or your LinkedIn profile
  saved as PDF, to fill the memory in one go.
- **Preferences.** Say things like *"always use UK spelling"* or *"keep it to
  one page"*. They're remembered and applied to every rebuild.
- **Compare.** With an application's CV open, **Compare** shows it next to your
  general CV (or any other application's), with changed wording highlighted:
  added words in green, removed words struck through in red, and whole bullets
  that were added or dropped marked. Check what was tailored before you send it.
- **Is it all true?** In the CV check, **Check it's all true** has the AI compare
  every line of the CV with your memory and list anything it can't back up:
  a number that's different, a tool you never mentioned, "led" where you
  "helped". Use its truthful suggestion, remove the line, or, if it is true,
  add the missing fact to your memory. Worth running before sending a tailored CV.
- **Strengthen my CV.** Under *Tell me something new*, **Answer a few questions**
  asks up to six specific questions about your own work (mostly the numbers
  behind it: how many users, samples, hours saved). Answer the ones you can and
  they go into your memory. It works without an AI model too, with simpler questions.
- **PhD applications.** In **New application**, choose *A PhD, master's by
  research or research position*. You get an academic CV (Education first, then
  Research Experience, Publications & Presentations, Teaching Experience, Awards &
  Scholarships), research-focused wording, a **statement of purpose** instead of
  a cover letter, and PhD-style interview prep. Paste the programme page or the
  lab's research as its description.
- **Email a professor.** In the Applications tab, **Email a professor**: type
  their name and university and the app finds them in
  [OpenAlex](https://openalex.org), a free, open index of academic papers. Pick
  the right person (names clash, so it shows their university, topics and paper
  count), see their recent and most-cited papers, then **Draft the email**: a
  short first email that mentions one of their papers and connects it to your
  own work, asks if they're taking PhD students, and mentions your CV. It's
  saved as a PhD application with an academic CV, so you can track it.
- **Interview prep.** Open an application and go to **Interview prep** for the
  8-10 questions you're most likely to be asked for that job, with talking points
  from your real experience, and good questions to ask them.
- **LinkedIn.** The **LinkedIn** tab writes a headline, an About section and a
  description for each job from your memory, with copy buttons, so your profile
  matches your CV.
- **Job ads from a link.** In **New application**, paste the link and click
  **Get the ad from this link**. Some sites (LinkedIn, for example) only show the
  ad when you're logged in; then copy and paste it instead.
- **Follow-ups.** Applications marked *Applied* a week ago or more without a
  follow-up are flagged (with a count on the Applications tab), with a button to
  draft a short, polite follow-up email. Copy it or open it in your email app,
  then mark it as sent.
- **Countries and languages.** Above the CV, choose the country whose
  conventions to follow: **Hong Kong** (British spelling, languages you speak
  easy to find, a photo is fine), **United States** (a one-page résumé, American
  spelling, no photo or personal details) or **United Kingdom** (British
  spelling, no photo). Choose **Traditional** or **Simplified Chinese** to get a
  translated CV; company and university names are kept. Each application can
  have its own country and language.
- **Photo.** **Photo** above the CV adds one to the header. It's shown only for
  countries where photos are expected, and never on the ATS-safe PDF.
- **AI usage.** Under the model in the AI model box, a line shows roughly what
  your API key has cost this month; click it for a breakdown by task. Costs are
  estimated from Anthropic's list prices; other services show tokens (check
  their billing page for exact costs). Local models are free.
- **Downloads.** **Download PDF** saves a PDF straight away, made by the Chrome,
  Edge or Brave browser already on your computer: selectable text (which
  applicant-tracking systems need), your template, no browser header or footer.
  If none of those browsers is installed, the print dialog opens instead;
  choose *Save as PDF*. **Word** downloads a .docx for portals that ask for one.
  Both work for the CV and the cover letter. Under **More**, the **ATS-safe PDF**
  is a plain single column in a standard font with dates written inline, which
  screening software reads reliably; use it for online application portals. The
  **Plain text** version is for forms that ask you to paste your CV.

## Setup

Requires Python 3.10+ (get it from https://www.python.org/downloads/).

**Easiest:** double-click **`start.command`** (Mac) or **`start.bat`** (Windows)
in the project folder. The first time, it sets everything up (about a minute).
After that it starts the app and opens it in your browser. Keep its window open
while you use the app; close it to stop. (On a Mac, if it says the file can't
be opened, right-click it, choose **Open**, then **Open** again.)

**As a Mac app:** double-click **`make_mac_app.command`** once. It adds
**CV Maker** (with its own icon) to your Applications folder, so you can open it
from Spotlight, Launchpad or the Dock like any app. There's no window to keep
open: it runs in the background and stops by itself about 15 minutes after you
close its page. If you move the project folder, run `make_mac_app.command` again.

**Or from a terminal**, using a virtual environment (a private folder of
packages just for this project):

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m cv_maker                 # opens http://127.0.0.1:5000 in your browser
```

Each time you open a new terminal, run `source .venv/bin/activate` again
before starting the app. Your prompt shows `(.venv)` when it's active. If port
5000 is taken (macOS uses it for AirPlay), the app picks the next free one.

### Option A: free local model (Ollama)

1. Install Ollama from https://ollama.com/download and open it.
2. Start the app (double-click `start.command` / `start.bat`, or `python -m cv_maker`).
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
- **Quality.** Local models write weaker CVs than hosted models. Check the
  result, and fix wording directly on the CV.
- **PDFs.** Attached PDFs are converted to text first, so scanned (image-only)
  PDFs won't work; paste the text instead. Word files work with every model.

### Option B: your own API key (paid, best quality)

Choose **Use an API key…** in the AI model box and paste a key. The app works
out which service it's for from the key's format (or pick the service from the
list; for any other OpenAI-compatible service, choose *Other* and enter its API
address). The key is checked with the service, then saved only in
`data/secrets.json` on your computer (readable only by you), and never shown on
the page again. After that, pick which of that service's models to use.
**Remove key** deletes it. You can switch between your API key and a free local
model at any time; your memory and CVs carry over. An Anthropic key in the
`ANTHROPIC_API_KEY` environment variable also works.

`--ai` sets the starting choice before anything has been picked on the page:

```bash
python -m cv_maker --ai ollama    # start with the local model
python -m cv_maker --ai api       # start with your API key
python -m cv_maker --ai none      # start with no AI: plain layout, edit memory by hand
```

### Options

| Flag / env var | Default | Meaning |
| --- | --- | --- |
| `--ai` / `CV_MAKER_AI` | `auto` | Starting choice: `auto`, `api`, `ollama` or `none` |
| `--data` / `CV_MAKER_DATA` | `data/` | Where your memory and CV are stored |
| `--port` | `5000` or the next free one | Port to serve on |
| `--no-browser` | | Don't open the page automatically |
| `CV_MAKER_OLLAMA_MODEL` | `qwen3:4b` | Starting local model, before one is picked on the page |
| `CV_MAKER_OLLAMA_CONTEXT` | `16384` | Local model context size; raise it if you see "ran out of room" |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Where Ollama is running |
| `CV_MAKER_MODEL` | `claude-opus-5-5` | Default model for an Anthropic key |

## How the AI is used

Whichever model you pick, the app lays out the CV itself (newest first,
consistent section names and formatting) and the model only writes the wording:
the summary, bullet points and skills. When memory is updated, the model only
reports what changed and the app merges it, so an update can't accidentally
wipe existing entries. Wording for entries that haven't changed is reused, so
rebuilds are quicker and, with an API key, cheaper.

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
| `secrets.json` | Your API key and which service it's for, if you added one on the page |
| `wording_cache.json` | Local model's wording, reused so unchanged entries aren't rewritten |
| `versions/<id>/prep.json`, `professor.json` | Interview prep, and a professor's research found for a PhD application |
| `linkedin.json` | Your LinkedIn text |
| `photo.jpg` | Your CV photo, if you added one |
| `usage.jsonl` | Tokens used per AI request, for the usage and cost line |

`data/` is in `.gitignore` so personal details aren't committed by accident.
Back it up, or point `--data` at a private folder or repository.

Looking up a professor sends their name to OpenAlex, and **Get the ad from
this link** fetches that page; nothing about you is sent. With the local model,
nothing else leaves your computer. With an API key, your memory
and any files you attach are sent to that service when you add something or
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
| `cv_maker/backend.py` | Shared logic for every model: prompts, memory updates, CV wording and its cache |
| `cv_maker/ai.py` | Anthropic-key backend (also reads scanned PDFs) |
| `cv_maker/api_models.py`, `providers.py` | API keys for OpenAI-compatible services, and recognising which service a key is for |
| `cv_maker/writing.py` | Prompts shared by both backends: bullet rewrites and cover letters |
| `cv_maker/export.py` | PDF (via a local Chrome-based browser) and Word downloads |
| `cv_maker/ollama.py` | Local-model backend (Ollama): installed models, downloads |
| `cv_maker/models.py` | The AI model picker: choosing, downloading and switching models |
| `cv_maker/render.py`, `templates/cv.html.j2` | CV HTML, plus the no-AI fallback layout |
| `cv_maker/app.py` | Flask routes |
| `cv_maker/static/` | Browser UI: `app.js` (main), `assist.js` (bullet help, cover letter), `cv.css` (the CV's look on screen and in print) |

To change how the CV looks, edit `cv_maker/static/cv.css`. To change how the CV
is worded, edit `CV_WORDING_SYSTEM` in `cv_maker/backend.py`.
