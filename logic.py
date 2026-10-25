"""Connect free-text classification to the existing PNG creature assembler.

    python logic.py "A bear with a peacock tail"
    python logic.py --request-json examples/bear_peacock.json
    python logic.py --request-json examples/bear_peacock.json --dry-run

Import generate_creature() to use the same pipeline from another Python module.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import frankenstein
import parts_classification
from parts_classification import BodySlot, MAX_ANIMALS, MIN_LEGS, MonsterRequest, PartRequest

BASE_DIR = Path(__file__).resolve().parent
SLOT_MAP = {"torso": "body", "head": "head", "tail": "tail", "eyes": "eyes",
            "horn": "horns", "wings": "wings"}


@dataclass
class BuildPlan:
    filenames: list[str] = field(default_factory=list)
    leg_socket_indices: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pose: str | None = None

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


@dataclass
class GenerationResult:
    prompt: str
    request: MonsterRequest
    plan: BuildPlan
    outline: bool = True
    image_path: Path | None = None
    metadata_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "classification": self.request.model_dump(mode="json"),
            "filenames": self.plan.filenames,
            "leg_socket_indices": self.plan.leg_socket_indices,
            "pose": self.plan.pose,
            "warnings": self.plan.warnings,
            "outline": self.outline,
            "image_path": str(self.image_path) if self.image_path else None,
            "metadata_path": str(self.metadata_path) if self.metadata_path else None,
        }


def load_catalog() -> dict:
    """Use the assembler's socket catalog, not the speculative body-parts catalog."""
    return json.loads(frankenstein.LIBRARY.read_text(encoding="utf-8"))["parts"]


def plan_creature(request: MonsterRequest | dict, *, strict: bool = False) -> BuildPlan:
    """Translate a validated classification into existing filenames and sockets.

    Missing donors are substituted only within the existing three-animal limit.
    Unsupported parts/counts produce warnings, or a ValueError in strict mode.
    No image is written and no API is contacted here.
    """
    request = MonsterRequest.model_validate(request)
    catalog = load_catalog()
    available = {n: p for n, p in catalog.items() if frankenstein.part_path(n).is_file()}
    slots = {p.slot.value: p for p in request.parts}
    host = slots["torso"].animal.value
    plan = BuildPlan(pose=request.pose)
    # Reserve explicitly requested donors so a fallback cannot displace them.
    reserved_animals = {p.animal.value for p in request.parts}

    def select(part: PartRequest, *, role: str | None = None, index: int = 0):
        slot = "legs" if part.slot.value in {"front_legs", "back_legs"} else SLOT_MAP[part.slot.value]
        donor = part.animal.value
        candidates = [n for n, p in available.items() if p["slot"] == slot]
        if slot == "legs" and host != "fish":
            candidates = [n for n in candidates if not n.startswith("fish_")]
        if part.variant and part.variant.value == "fins":
            candidates = [n for n in candidates if "fin" in available[n].get("tags", [])]
        candidates = [n for n in candidates if n.split("_")[0] in reserved_animals
                      or len(reserved_animals) < MAX_ANIMALS]
        if not candidates:
            plan.warn(f"No available {part.slot.value} PNG fits the request and the {MAX_ANIMALS}-animal limit; omitted it.")
            return None

        def tags_for(name):
            animal = name.split("_")[0]
            return set(available[name].get("tags", [])) | set(parts_classification.animals[animal]["tags"])

        def score(name):
            animal = name.split("_")[0]
            tags = tags_for(name)
            side = ("left", "right")[index % 2] if animal == "peacock" else ("near", "far")[index % 2]
            tag_score = 5 * len(set(part.must) & tags) + len(set(part.prefer) & tags) - 5 * len(set(part.avoid) & tags)
            return (animal == donor, role in tags if role else False,
                    side in tags if role else False, tag_score, animal == host, animal == "dog")

        name = max(sorted(candidates), key=score)
        selected_animal = name.split("_")[0]
        reserved_animals.add(selected_animal)
        if selected_animal != donor:
            plan.warn(f"No usable {donor} {part.slot.value} PNG; used {selected_animal} instead.")
        missing = set(part.must) - tags_for(name)
        avoided = set(part.avoid) & tags_for(name)
        if missing:
            plan.warn(f"{name}.png does not supply these required traits: {', '.join(sorted(missing))}.")
        if avoided:
            plan.warn(f"{name}.png has traits the request avoids: {', '.join(sorted(avoided))}.")
        return name

    def add(part: PartRequest, parent_name: str, socket_slot: str):
        capacity = len(catalog[parent_name].get("sockets", {}).get(socket_slot, []))
        count = min(part.count, capacity)
        if count < part.count:
            plan.warn(f"Requested {part.count} {part.slot.value}; {parent_name} has {capacity} sockets, so kept {count}.")
        for i in range(count):
            name = select(part, index=i)
            if name:
                plan.filenames.append(f"{name}.png")

    torso_name = select(slots["torso"])
    if torso_name is None:
        raise ValueError("No torso PNG is available; check the Animal_PNGS folder.")
    host = torso_name.split("_")[0]
    plan.filenames.append(f"{torso_name}.png")
    # Older classifier outputs have no head slot. Keep those outputs usable.
    head_part = slots.get("head") or PartRequest(slot=BodySlot.HEAD, animal=slots["torso"].animal)
    head_name = select(head_part)
    if head_name is None:
        raise ValueError("No head PNG is available; check the Animal_PNGS folder.")
    plan.filenames.append(f"{head_name}.png")

    if "tail" in slots:
        add(slots["tail"], torso_name, "tail")

    leg_sockets = catalog[torso_name].get("sockets", {}).get("legs", [])
    used_sockets = set()
    attached_leg_count = 0
    for slot, role in (("front_legs", "front"), ("back_legs", "rear")):
        if slot not in slots:
            continue
        part = slots[slot]
        # Peacock sockets are left/right rather than front/rear. Use their order.
        indices = [i for i, socket in enumerate(leg_sockets)
                   if i not in used_sockets and (host == "peacock" or role in socket.get("prefer", []))]
        if part.count > len(indices):
            plan.warn(f"Requested {part.count} {slot}; {torso_name} has {len(indices)} available matching sockets, so kept {len(indices)}.")
        if part.variant and part.variant.value == "arms" and part.animal.value != "monkey":
            plan.warn("Arms use the selected animal's front-leg PNGs; this catalog has no separate hand/arm cutouts.")
        for ordinal, socket_index in enumerate(indices[:part.count]):
            name = select(part, role=role, index=ordinal)
            if name:
                plan.filenames.append(f"{name}.png")
                plan.leg_socket_indices.append(socket_index)
                used_sockets.add(socket_index)
                if part.variant is None or part.variant.value != "arms":
                    attached_leg_count += 1

    if attached_leg_count < MIN_LEGS:
        raise ValueError(f"The available leg PNGs and sockets cannot supply the required {MIN_LEGS} legs.")

    for slot, parent_name, socket_slot in (("eyes", head_name, "eyes"),
                                           ("horn", head_name, "horns"),
                                           ("wings", torso_name, "wings")):
        if slot in slots:
            add(slots[slot], parent_name, socket_slot)

    if "ears" in slots:
        ears = slots["ears"]
        if ears.animal.value != head_name.split("_")[0] or ears.count > 2:
            plan.warn(f"No separate ear PNGs exist. Kept the ears embedded in {head_name}.png; could not independently apply the requested ears.")

    if request.pose:
        supported = any(request.pose in socket.get("pose", {})
                        for parent_name in (torso_name, head_name)
                        for sockets in catalog[parent_name].get("sockets", {}).values()
                        for socket in sockets)
        if not supported:
            plan.warn(f"The catalog has no '{request.pose}' pose transforms; used the original part poses.")
            plan.pose = None
    if strict and plan.warnings:
        raise ValueError("Cannot exactly satisfy this request: " + " ".join(plan.warnings))
    return plan


def generate_creature(prompt: str = "", output_path: str | Path | None = None, *,
                      request: MonsterRequest | dict | None = None,
                      dry_run: bool = False, strict: bool = False,
                      outline: bool = True) -> GenerationResult:
    """Run prompt -> classify -> filenames -> renderer; return paths and diagnostics.

    Passing request= explicitly bypasses the API for reproducible offline tests.
    Each normal run saves a PNG plus a JSON record of the selected parts.
    """
    if request is None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Enter a non-empty creature description.")
        request = parts_classification.classify(prompt)
    request = MonsterRequest.model_validate(request)
    plan = plan_creature(request, strict=strict)
    result = GenerationResult(prompt=prompt, request=request, plan=plan, outline=outline)
    if dry_run:
        return result
    if output_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = BASE_DIR / "outputs" / f"creature_{stamp}_{uuid4().hex[:8]}.png"
    output_path = Path(output_path).expanduser().resolve()
    if output_path.suffix.lower() != ".png":
        raise ValueError("The output filename must end in .png.")
    result.image_path = frankenstein.create_creature(
        plan.filenames, output_path=output_path,
        leg_socket_indices=plan.leg_socket_indices, pose=plan.pose, outline=outline,
    )
    result.metadata_path = output_path.with_suffix(".json")
    result.metadata_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return result


def check_setup() -> dict:
    """Check local configuration without constructing a client or calling the API."""
    dependencies = {}
    for module in ("PIL", "pydantic", "dotenv", "google.genai"):
        try:
            dependencies[module] = importlib.util.find_spec(module) is not None
        except ModuleNotFoundError:
            dependencies[module] = False
    if dependencies["dotenv"]:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    catalog = load_catalog()
    missing = [str(frankenstein.part_path(name)) for name in catalog
               if not frankenstein.part_path(name).is_file()]
    key_configured = bool(parts_classification.get_api_key())
    return {"provider": "google-gemini", "model": parts_classification.get_model(),
            "dependencies": dependencies, "catalog_parts": len(catalog),
            "missing_pngs": missing, "api_key_configured": key_configured,
            "offline_ready": not missing,
            "prompt_ready": not missing and all(dependencies.values()) and key_configured}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt", nargs="?", help="Creature description (quote the full sentence)")
    parser.add_argument("-o", "--output", type=Path, help="Output PNG filename; default: outputs/creature_<unique-id>.png")
    parser.add_argument("--request-json", type=Path, help="Use a saved MonsterRequest instead of calling the classifier")
    parser.add_argument("--dry-run", action="store_true", help="Print classification and filenames without writing an image")
    parser.add_argument("--strict", action="store_true", help="Reject unsupported parts, fallback donors, or truncated counts")
    parser.add_argument("--show", action="store_true", help="Open the saved PNG in the computer's default image viewer")
    parser.add_argument("--no-outline", action="store_true", help="Do not draw the white border around each part")
    parser.add_argument("--check", action="store_true", help="Check assets, dependencies, and key presence without an API call")
    args = parser.parse_args(argv)
    try:
        if args.check:
            status = check_setup()
            print(json.dumps(status, indent=2))
            return 0 if status["offline_ready"] else 1
        request = None
        if args.request_json:
            request = json.loads(args.request_json.read_text(encoding="utf-8-sig"))
        prompt = args.prompt if args.prompt is not None else ("" if request is not None else input("Describe your creature: "))
        result = generate_creature(prompt, output_path=args.output, request=request,
                                   dry_run=args.dry_run, strict=args.strict,
                                   outline=not args.no_outline)
        if args.dry_run:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print("Selected PNGs: " + ", ".join(result.plan.filenames))
            for warning in result.plan.warnings:
                print("Warning: " + warning)
            print(f"Saved image: {result.image_path}")
            print(f"Saved details: {result.metadata_path}")
            if args.show:
                from PIL import Image
                with Image.open(result.image_path) as image:
                    image.show()
        return 0
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
