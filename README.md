# Monster Mash

## Creature Lab UI

The local browser UI includes manual animal-part selection, an AI description
tab, random combinations, rendered preview, PNG download, and assembly warnings.
Manual mode does not call Gemini. The engine allows two or three donor animals.

From this folder in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe ui_server.py
```

Open http://127.0.0.1:8000. The initial image is a labeled sample; click
**Bring it to life** to generate your selected creature. The **Surprise me**
button changes the ingredients; click **Bring it to life** to assemble them.
For the AI tab, configure the existing `.env` as described below.

UI files are in `frontend/`: `index.html` is the layout, `style.css` controls
the visual design and responsive layout, and `app.js` handles interaction.
`ui_server.py` connects `POST /api/create` to `logic.generate_creature()` and
serves only frontend files and PNG assets. API keys stay on the server.
Use this loopback-only server for local development.

Build a creature PNG from the animal cutouts in `Animal_PNGS`. This edition uses
Google Gemini through the official `google-genai` Python SDK for prompt classification.

```text
User description -> parts_classification.classify() using Gemini structured JSON
                 -> logic.plan_creature() chooses existing PNG filenames
                 -> frankenstein.create_creature() attaches the parts
                 -> outputs/creature_<unique-id>.png and matching .json
```

See [RUN_LOGIC.md](RUN_LOGIC.md) for installation, API configuration, offline tests,
PowerShell commands, examples, and current asset limitations.

Quick start after installing `requirements.txt` and configuring `.env`:

```dotenv
GEMINI_API_KEY=your_google_ai_studio_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
```

```bash
python logic.py "A bear with a peacock tail" --show
```

Test assembly without an API call:

```bash
python logic.py --request-json examples/bear_peacock.json --output outputs/bear_peacock.png
python -m unittest discover -s tests -v
```
