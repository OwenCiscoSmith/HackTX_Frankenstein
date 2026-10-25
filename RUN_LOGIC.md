# Run and check logic.py with Google Gemini

This edition switches the classifier from OpenAI to Google's Gemini API. The
official `google-genai` SDK requests structured JSON, validates it using the
existing `MonsterRequest` model, then sends the selected PNG filenames to the
existing renderer. Changing only the API key in the old code cannot make that switch.

## 1. Put the update in your existing project

This update was developed against repository commit `558afcfa6c413cdfc2dd09d9bb084418330738ab`.

Extract the update ZIP and copy its contents into the existing `HackTX_Frankenstein`
folder. Allow the updated Python files to replace their earlier versions. Keep the
existing `Animal_PNGS` folder and your existing `.env` file.

The important files must be at the same level:

| Path | Purpose |
| --- | --- |
| `logic.py` | Receives the prompt, calls classification, selects PNGs, and requests the final image. |
| `parts_classification.py` | Gemini classifier using structured JSON, heads, portable paths, and lazy API initialization. |
| `frankenstein.py` | Existing renderer, updated for multiple eyes/horns/wings, correct leg sockets, and donated tails on bear torsos. |
| `structure.py` | Provider-independent asset geometry schemas; unused OpenAI initialization was removed. |
| `Animal_PNGS/animal_library.json` | Existing attachment/socket catalog used by the renderer. |
| `Animal_PNGS/animals.json` | Existing animal trait vocabulary used by classification and part selection. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Blank configuration template; contains no API key. |
| `examples/` | Two repeatable classifications for testing without API calls. |
| `tests/test_logic.py` | Local tests using real cutouts and a mocked external classifier response. |

The ZIP is a code update, so it does not duplicate the existing animal images.
The included `sample_output/bear_peacock.png` shows one verified output.

## 2. Open PowerShell in the project root

Use your actual local folder path:

```powershell
cd "C:\path\to\HackTX_Frankenstein"
Get-ChildItem logic.py, parts_classification.py, frankenstein.py, Animal_PNGS
```

Use Python 3.10 or later. The update was tested with Python 3.12.

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

These commands use the virtual environment directly, so PowerShell activation is
not required. If Windows does not provide `py`, use `python` for the first two
commands. On macOS/Linux, create the environment with `python3 -m venv .venv` and
use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe` below.

## 3. Check local setup without making an API call

```powershell
.\.venv\Scripts\python.exe logic.py --check
```

For the repository snapshot, the expected `catalog_parts` value is `78` and
`missing_pngs` should be empty. `offline_ready` should be `true`.
`provider` should be `google-gemini`, and `model` should match `GEMINI_MODEL`.
`prompt_ready` becomes `true` when the local files, dependency packages and a Google
API key are present. This check does not validate the key, provider connection, or quota.

## 4. Check filename selection without generating an image

```powershell
.\.venv\Scripts\python.exe logic.py --request-json examples/bear_peacock.json --dry-run
```

The printed JSON should contain these filenames:

```json
[
  "bear_torso.png",
  "bear_head.png",
  "peacock_tail.png",
  "bear_leg_front_near.png",
  "bear_leg_front_far.png",
  "bear_leg_rear_near.png",
  "bear_leg_rear_far.png",
  "bear_eye.png"
]
```

The leg socket indices should be `[0, 2, 1, 3]`. Front and rear legs therefore attach
to their correct positions even though they are listed in separate groups.
This command makes no API call and writes no image.

## 5. Generate and open an image without an API key

```powershell
.\.venv\Scripts\python.exe logic.py --request-json examples/bear_peacock.json --output outputs/bear_peacock.png --show
```

Expected files:

- `outputs/bear_peacock.png`: a 1000 x 1000 transparent PNG.
- `outputs/bear_peacock.json`: the classification, chosen filenames, socket indices,
  warnings and output paths.

To inspect repeated eyes, horns and wings:

```powershell
.\.venv\Scripts\python.exe logic.py --request-json examples/three_animal_monster.json --output outputs/three_animal_monster.png --show
```

That example requests a lion body/head/legs, four lion eyes, two narwhal horns,
and two peacock wings. This is a deliberate three-animal combination. Original
cutout quality, especially for lion and narwhal assets, affects the final appearance.

The renderer adds a white outline around each part by default. To omit the outline
for a lion-and-peacock creature, use the included offline example:

```powershell
.\.venv\Scripts\python.exe logic.py --request-json examples/lion_peacock.json --output outputs/lion_peacock_no_outline.png --no-outline --show
```

Remove `--no-outline` to keep the white cutout borders. The outline choice is
recorded in the matching JSON metadata file.

## 6. Configure the Gemini prompt classifier

Create or obtain your organization's Gemini API key through
[Google AI Studio](https://aistudio.google.com/api-keys). Google documents the
setup in [Using Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key).

Use `GEMINI_API_KEY` in `.env`. `GOOGLE_API_KEY` is also accepted; when both
variables are set, `GOOGLE_API_KEY` takes precedence, following Google's SDK
convention. Use one variable to avoid confusion. Existing operating-system
environment variables take priority over values in `.env`.

If you have no `.env` yet:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Replace the old OpenAI settings in that local file with:

```dotenv
GEMINI_API_KEY=your_actual_google_ai_studio_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
```

The `.env` file belongs beside `logic.py`. The Gemini classifier ignores
`OPENAI_API_KEY`, `OPEN_AI`, and `OPENAI_MODEL`. Use a Google AI Studio key for
this version. Keep it private. No key is required for JSON test mode, imports,
or local unit tests. The update ZIP includes a blank `.env.example`; it does
not contain or overwrite your private `.env`.

`gemini-3.5-flash-lite` is the default for this small classification task. If your
organization uses another supported model, change only `GEMINI_MODEL`, for
example to `gemini-3.8-flash`. Check access for your Google project. The key
does not by itself guarantee model access, available quota, or free usage.

The implementation follows Google's current Interactions API, using a JSON
response schema and `store=False` for independent one-turn classifications.
It does not send your animal PNGs to Gemini; the image is assembled locally.

## 7. Give a natural-language prompt

```powershell
.\.venv\Scripts\python.exe logic.py "A bear with a peacock tail, four bear legs, a bear head and one bear eye. No wings or horns." --output outputs/my_creature.png --show
```

Or type the description interactively:

```powershell
.\.venv\Scripts\python.exe logic.py
```

Without `--output`, each run gets a unique filename under the project's `outputs`
folder. With `--output`, rerunning the same path replaces that PNG and its JSON.

To inspect the classifier result and selected filenames before rendering:

```powershell
.\.venv\Scripts\python.exe logic.py "A dog body with a lion head and a peacock tail" --dry-run
```

Natural-language `--dry-run` still calls the external classifier. Only
`--request-json` bypasses that call.

## 8. Run the local tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests exercise the real catalog and PNG renderer. External API responses
are mocked; the local pipeline, filenames, socket placement, generated PNG
and JSON are tested together. An additional test uses the real Google SDK with
a local HTTP mock transport to verify the request schema, authentication header,
model selection, and response parsing without an external API call.

## Calling the pipeline from another Python file

```python
from logic import generate_creature

result = generate_creature(
    "A bear with a peacock tail",
    output_path="outputs/from_python.png",
)
print(result.image_path)
print(result.plan.filenames)
print(result.plan.warnings)
```

`generate_creature()` is synchronous. It returns `GenerationResult`, including the
image path and the structured classification. `result.to_dict()` gives a
JSON-serializable result for later application integration.

## Existing limits and fallback behavior

- The classifier keeps the existing limit of three donor animals and at least two
  legs. Arms do not count as legs. A no-legs request fails validation.
- The renderer supports one torso and one head. Current bodies have one tail
  socket and four total leg sockets. Current heads have four eye and horn sockets;
  bodies have four wing sockets. Unsupported counts are capped with a warning.
- Front and rear leg counts are limited by matching sockets. Normal four-legged
  bodies have two front and two rear sockets. Peacock sockets use left/right order.
- Ears are embedded in head cutouts. They cannot be independently swapped from
  another animal because the renderer's catalog has no separate ear assets.
  There are also no separate nose, lip, or hand assets in this pipeline's catalog.
- The mapper selects only existing PNGs. When an animal cannot supply a requested
  part, it chooses a real alternative within the three-animal limit and reports
  that substitution, or omits the optional part with a warning if none is possible.
- The lizard's missing rear-far leg reuses its real rear-near cutout. Narwhals have
  no leg cutouts, so they need donated legs. Fish leg/fin cutouts remain restricted
  to fish torsos, following the classifier's original rule.
- Trait tags guide selection among available cutouts. They do not recolor images
  or synthesize new anatomy. Unsatisfied required traits are reported.
- Only poses with socket transforms can alter assembly. Unsupported poses are
  reported and use the original cutout poses.
- Add `--strict` to fail on substitutions, unsupported traits, or count truncation
  before an image is written. This does not verify the external classifier's
  interpretation of the original sentence; inspect the saved classification for that.

## Troubleshooting

| Message/problem | What to check |
| --- | --- |
| `No module named ...` | Install `requirements.txt` using the same interpreter that runs `logic.py`. |
| `Set GEMINI_API_KEY ...` | Put `GEMINI_API_KEY` or `GOOGLE_API_KEY` in `.env` beside the Python files, or use the JSON test mode. |
| `Gemini classification failed (...ClientError)` | Check your Google key, project/API permissions, `GEMINI_MODEL`, and quota in AI Studio. The message deliberately omits raw provider details that might expose a key. |
| `Gemini classification failed (...ServerError)` | Retry after a temporary provider failure. |
| `Gemini returned no classification text` | The model did not produce a usable text response. Try a more specific description. |
| `Gemini returned a classification that does not match ...` | The output failed schema or creature-rule validation. Try a more specific request using at most three animals and at least two legs. |
| A connection/timeout classification error | Check network access and proxy settings. |
| A SOCKS proxy error mentioning `socksio` | If your environment uses a SOCKS proxy, install it with `.\.venv\Scripts\python.exe -m pip install "httpx[socks]"`. |
| Missing PNGs | Restore the existing `Animal_PNGS` tree at the same level as the Python files; use `--check` for exact paths. |
| Image did not open | The file is still saved at the printed path. Open it manually or run with `--show`. |
| Body part looks rough or has seams | The code uses existing cutouts and white outlines. Output quality follows those assets and attachment coordinates. |

## Google references used for this update

- [API key setup](https://ai.google.dev/gemini-api/docs/api-key)
- [SDK quickstart](https://ai.google.dev/gemini-api/docs/get-started)
- [Structured JSON outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
- [Official Google Gen AI Python SDK](https://github.com/googleapis/python-genai)
