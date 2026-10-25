import json
import random
import sys
from pathlib import Path
from PIL import Image, ImageFilter

ANIMALS_DIR = Path(__file__).parent / "Animal_PNGS"
LIBRARY = ANIMALS_DIR / "animal_library.json"
OUTPUT = ANIMALS_DIR / "random_frankenstein.png"
# Final image is OUTPUT_SIZE x OUTPUT_SIZE; creatures larger than that are scaled down to fit
OUTPUT_SIZE = 1000
# Thickness in pixels of the white border around each part
OUTLINE_WIDTH = 5

# The lion parts are badly cut and need re-cutting, so random mode skips them for now
EXCLUDE = {"lion", "narwhal"}
ANIMALS = [a for a in ["elephant", "peacock", "monkey", "bear", "dog", "fish", "alligator", "lion", "lizard", "narwhal"]
           if a not in EXCLUDE]
HAS_TAIL = [a for a in ["elephant", "monkey", "peacock", "fish", "dog", "alligator", "lion", "lizard", "narwhal"]
            if a not in EXCLUDE]
# Swapped-in heads are kept between these fractions of the host torso's height
HEAD_RATIO = (0.45, 0.9)
# Leg parts in the order of each torso's leg sockets
LEGS = {
    "elephant": ["elephant_leg_front_near", "elephant_leg_rear_near",
                 "elephant_leg_front_far", "elephant_leg_rear_far"],
    "peacock": ["peacock_leg_left", "peacock_leg_right"],
    "monkey": ["monkey_leg_front_near", "monkey_leg_rear_near",
               "monkey_leg_front_far", "monkey_leg_rear_far"],
    "bear": ["bear_leg_front_near", "bear_leg_rear_near",
             "bear_leg_front_far", "bear_leg_rear_far"],
    "dog": ["dog_leg_front_near", "dog_leg_rear_near",
            "dog_leg_front_far", "dog_leg_rear_far"],
    "fish": ["fish_leg_front_near", "fish_leg_rear_near"],
    "alligator": ["alligator_leg_front_near", "alligator_leg_rear_near",
                  "alligator_leg_front_far", "alligator_leg_rear_far"],
    "lion": ["lion_leg_front_near", "lion_leg_rear_near",
             "lion_leg_front_far", "lion_leg_rear_far"],
    "lizard": ["lizard_leg_front_near", "lizard_leg_rear_near",
               "lizard_leg_front_far"],
    "narwhal": []
}
# What each leg socket index means on every torso (they alternate front/rear)
LEG_ROLES = ["front_near", "rear_near", "front_far", "rear_far"]


def socket_count(animal):
    """Number of leg sockets on an animal's torso (a peacock has 2, most others 4)."""
    return 2 if animal == "peacock" else 4


def leg_for(animal, socket_index):
    """The animal's leg for a socket, falling back when that exact leg image is missing."""
    legs = LEGS[animal]
    if not legs:
        return None
    role = LEG_ROLES[socket_index % 4]
    for candidate in (role, role.split("_")[0] + ("_far" if role.endswith("near") else "_near")):
        if f"{animal}_leg_{candidate}" in legs:
            return f"{animal}_leg_{candidate}"
    # Animals without front/rear naming (peacock) just use their legs in order
    return legs[socket_index % len(legs)]


# Animals that can donate legs (the narwhal has none)
LEGGED = [a for a in ANIMALS if LEGS[a]]

# Optional head and body attachments that can be added to any creature
HORNS = ["peacock_crest", "narwhal_horn"]
WINGS = ["peacock_wing", "fish_wing", "narwhal_wing_far", "narwhal_wing_near"]
# Chance that each optional part is added
OPTIONAL_CHANCE = 0.5
# Makes swapped-in parts that had to be shrunk larger than the fitted size
SIZE_MULTIPLIER = 4


def load_part(name):
    # Part names are prefixed with their animal, which names the folder:
    # Animal_PNGS/<animal>/<animal>_parts/<part name>.png
    animal = name.split("_")[0]
    return Image.open(ANIMALS_DIR / animal / f"{animal}_parts" / f"{name}.png").convert("RGBA")


def bbox_size(img):
    x0, y0, x1, y1 = img.getbbox()
    return x1 - x0, y1 - y0


def add_outline(img, width=OUTLINE_WIDTH):
    """Return img with an opaque white border of `width` px around its visible pixels."""
    alpha = img.getchannel("A").point(lambda a: 255 if a > 10 else 0)
    # Grow the silhouette by `width` px, rounding it by alternating square and diamond steps
    grown = alpha
    for i in range(width):
        grown = grown.filter(ImageFilter.MaxFilter(3))
        if i % 2:
            grown = grown.filter(ImageFilter.GaussianBlur(0.8)).point(lambda a: 255 if a > 128 else 0)
    out = Image.new("RGBA", img.size, (255, 255, 255, 0))
    out.putalpha(grown)
    out.alpha_composite(img)
    return out


def fit_scale(img, ref_img):
    """Scale that makes img's visible area fit inside ref_img's; boosted when shrinking."""
    w, h = bbox_size(img)
    rw, rh = bbox_size(ref_img)
    scale = min(rw / w, rh / h)
    return min(1.0, scale * SIZE_MULTIPLIER) if scale < 1 else scale


def random_parts(rng):
    """Pick a random set of part filenames that build() can assemble."""
    host = rng.choice(ANIMALS)
    names = [f"{host}_torso", f"{rng.choice(ANIMALS)}_head", f"{rng.choice(HAS_TAIL)}_tail"]

    # Sockets alternate front, rear, front, rear, so one donor animal supplies every
    # front leg and another supplies every rear leg
    front_donor, rear_donor = rng.choice(LEGGED), rng.choice(LEGGED)
    for i in range(socket_count(host)):
        donor = front_donor if i % 2 == 0 else rear_donor
        names.append(leg_for(donor, i))
    names.append(f"{rng.choice(ANIMALS)}_eye")
    if rng.random() < OPTIONAL_CHANCE:
        names.append(rng.choice(HORNS))
    if rng.random() < OPTIONAL_CHANCE:
        names.append(rng.choice(WINGS))
    return [f"{n}.png" for n in names]


def build(filenames):
    """Assemble an image from part filenames, e.g. ["monkey_torso.png", "elephant_head.png"].

    Needs exactly one torso. Legs attach to the torso's leg sockets in the order given.
    """
    parts = json.loads(LIBRARY.read_text())["parts"]
    layers = []  # (z, image, offset)
    chosen = [Path(f).stem for f in filenames]
    unknown = [n for n in chosen if n not in parts]
    if unknown:
        raise ValueError(f"Unknown parts: {', '.join(unknown)}")

    by_slot = {}
    for n in chosen:
        by_slot.setdefault(parts[n]["slot"], []).append(n)
    for slot in ("body", "head", "tail", "eyes", "horns", "wings"):
        if len(by_slot.get(slot, [])) > 1:
            raise ValueError(f"Only one {slot} part allowed, got {by_slot[slot]}")
    if "body" not in by_slot:
        raise ValueError("A torso part is required")
    chosen = []  # rebuilt below in attach order

    def attach(parent, name, slot, idx, scale):
        p_off, p_scale, p_name = parent
        socket = parts[p_name]["sockets"][slot][idx]
        sx, sy = socket["at"]
        px, py = parts[name]["plug"]
        img = load_part(name)
        if scale != 1.0:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        # Socket angle is clockwise
        angle = socket.get("angle", 0)
        if angle:
            img = img.rotate(-angle, resample=Image.BICUBIC, center=(px * scale, py * scale))
        off = (round(p_off[0] + sx * p_scale - px * scale),
               round(p_off[1] + sy * p_scale - py * scale))
        layers.append((parts[name]["z"], img, off))
        chosen.append(name)
        return off, scale, name, img

    def scale_for(name, host_ref_name):
        if name.split("_")[0] == host_ref_name.split("_")[0]:
            return 1.0
        return fit_scale(load_part(name), load_part(host_ref_name))

    torso_name = by_slot["body"][0]
    host = torso_name.split("_")[0]
    torso_img = load_part(torso_name)
    layers.append((parts[torso_name]["z"], torso_img, (0, 0)))
    chosen.append(torso_name)
    torso = ((0, 0), 1.0, torso_name)

    head = None
    if "head" in by_slot:
        head_name = by_slot["head"][0]
        if head_name.split("_")[0] == host:
            head_scale = 1.0
        else:
            # Match the host's head height, clamped to a sane fraction of the torso height
            torso_h = bbox_size(torso_img)[1]
            target = min(max(bbox_size(load_part(f"{host}_head"))[1], HEAD_RATIO[0] * torso_h),
                         HEAD_RATIO[1] * torso_h)
            head_img = load_part(head_name)
            hw, hh = bbox_size(head_img)
            head_scale = min(target / hh, 1.0 * torso_h / hw)
        head = attach(torso, head_name, "head", 0, head_scale)
    if ("eyes" in by_slot or "horns" in by_slot) and head is None:
        raise ValueError("Eyes and crests need a head part")

    if "tail" in by_slot and f"{host}_tail" in parts:
        tail_name = by_slot["tail"][0]
        attach(torso, tail_name, "tail", 0, scale_for(tail_name, f"{host}_tail"))

    legs = by_slot.get("legs", [])
    socket_count = len(parts[torso_name]["sockets"]["legs"])
    if len(legs) > socket_count:
        raise ValueError(f"{torso_name} only has {socket_count} leg sockets, got {len(legs)} legs")
    if len(legs) > 0:
        for i, leg_name in enumerate(legs):
            # Legs are sized to the host's own leg; a legless host (narwhal) leaves them unscaled
            host_leg = leg_for(host, i)
            scale = scale_for(leg_name, host_leg) if host_leg else 1.0
            attach(torso, leg_name, "legs", i, scale)

    # Face parts are sized relative to the (possibly resized) head
    if head:
        head_animal = head[2].split("_")[0]
        head_scale, head_width = head[1], bbox_size(head[3])[0]
        if "eyes" in by_slot:
            eye_name = by_slot["eyes"][0]
            eye_scale = head_scale * scale_for(eye_name, f"{head_animal}_eye")
            attach(head[:3], eye_name, "eyes", 0, eye_scale)
        if "horns" in by_slot:
            # Sized as if on its own animal's head, scaled to this head
            horn_name = by_slot["horns"][0]
            own_head = bbox_size(load_part(f"{horn_name.split('_')[0]}_head"))[0]
            attach(head[:3], horn_name, "horns", 0, head_width / own_head)

    if "wings" in by_slot:
        wing_name = by_slot["wings"][0]
        own_torso = bbox_size(load_part(f"{wing_name.split('_')[0]}_torso"))[1]
        attach(torso, wing_name, "wings", 0, bbox_size(torso_img)[1] / own_torso)

    # Give every part its own white border, like a cut-out in a ransom note
    layers = [(z, add_outline(img), off) for z, img, off in layers]

    # Work on a canvas covering every part's visible pixels so nothing is clipped
    bounds = []
    for _, img, off in layers:
        x0, y0, x1, y1 = img.getbbox()
        bounds.append((off[0] + x0, off[1] + y0, off[0] + x1, off[1] + y1))
    left, top = min(b[0] for b in bounds), min(b[1] for b in bounds)
    right, bottom = max(b[2] for b in bounds), max(b[3] for b in bounds)

    canvas = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    # Draw back-to-front by z
    for _, img, off in sorted(layers, key=lambda l: l[0]):
        layer = Image.new("RGBA", (right - left + img.width, bottom - top + img.height), (0, 0, 0, 0))
        layer.paste(img, (off[0] - left, off[1] - top))
        canvas.alpha_composite(layer.crop((0, 0, canvas.width, canvas.height)))

    # Shrink (never enlarge) to fit the output size, then center on the output canvas
    shrink = min(1.0, OUTPUT_SIZE / canvas.width, OUTPUT_SIZE / canvas.height)
    if shrink < 1.0:
        canvas = canvas.resize((max(1, round(canvas.width * shrink)), max(1, round(canvas.height * shrink))),
                               Image.LANCZOS)
    final = Image.new("RGBA", (OUTPUT_SIZE, OUTPUT_SIZE), (0, 0, 0, 0))
    final.paste(canvas, ((OUTPUT_SIZE - canvas.width) // 2, (OUTPUT_SIZE - canvas.height) // 2))
    return final, chosen


if __name__ == "__main__":
    # python frankenstein.py                 -> random parts
    # python frankenstein.py 42              -> random parts from seed 42
    # python frankenstein.py a.png b.png ... -> exactly those parts
    args = sys.argv[1:]
    if args and not args[0].isdigit():
        image, chosen = build(args)
        print(f"Parts: {', '.join(chosen)}")
    else:
        seed = int(args[0]) if args else random.randrange(10**6)
        image, chosen = build(random_parts(random.Random(seed)))
        print(f"Seed {seed}: {', '.join(chosen)}")
    image.save(OUTPUT)
    print(f"Saved {OUTPUT}")