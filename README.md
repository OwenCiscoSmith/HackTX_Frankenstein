# HackTX Frankenstein

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
