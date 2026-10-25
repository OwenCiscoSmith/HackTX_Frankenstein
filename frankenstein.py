import json
import random
import sys
from pathlib import Path
from PIL import Image

ANIMALS_DIR = Path(__file__).parent / "Animal_PNGS"
LIBRARY = ANIMALS_DIR / "animal_library.json"
OUTPUT = ANIMALS_DIR / "random_frankenstein.png"

ANIMALS = ["elephant", "peacock"]
# Leg parts in the order of each torso's leg sockets
LEGS = {
    "elephant": ["elephant_leg_front_near", "elephant_leg_rear_near",
                 "elephant_leg_front_far", "elephant_leg_rear_far"],
    "peacock": ["peacock_leg_left", "peacock_leg_right"],
}
# Chance that each optional part is added
OPTIONAL_CHANCE = 0.5
# Makes swapped-in parts that had to be shrunk larger than the fitted size
SIZE_MULTIPLIER = 5


def load_part(name):
    # Part names are prefixed with their animal, which names the folder:
    # Animal_PNGS/<animal>/<animal>_parts/<part name>.png
    animal = name.split("_")[0]
    return Image.open(ANIMALS_DIR / animal / f"{animal}_parts" / f"{name}.png").convert("RGBA")


def bbox_size(img):
    x0, y0, x1, y1 = img.getbbox()
    return x1 - x0, y1 - y0


def fit_scale(img, ref_img):
    """Scale that makes img's visible area fit inside ref_img's; boosted when shrinking."""
    w, h = bbox_size(img)
    rw, rh = bbox_size(ref_img)
    scale = min(rw / w, rh / h)
    return min(1.0, scale * SIZE_MULTIPLIER) if scale < 1 else scale


def build(rng):
    parts = json.loads(LIBRARY.read_text())["parts"]
    layers = []  # (z, image, offset)
    chosen = []

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

    host = rng.choice(ANIMALS)
    torso_img = load_part(f"{host}_torso")
    layers.append((parts[f"{host}_torso"]["z"], torso_img, (0, 0)))
    chosen.append(f"{host}_torso")
    torso = ((0, 0), 1.0, f"{host}_torso")

    head_name = f"{rng.choice(ANIMALS)}_head"
    head = attach(torso, head_name, "head", 0, scale_for(head_name, f"{host}_head"))
    head_animal = head_name.split("_")[0]
    head_scale, head_width = head[1], bbox_size(head[3])[0]

    tail_name = f"{rng.choice(ANIMALS)}_tail"
    attach(torso, tail_name, "tail", 0, scale_for(tail_name, f"{host}_tail"))

    for i in range(len(LEGS[host])):
        donor = rng.choice(ANIMALS)
        leg_name = LEGS[donor][i % len(LEGS[donor])]
        attach(torso, leg_name, "legs", i, scale_for(leg_name, LEGS[host][i]))

    eye_name = f"{rng.choice(ANIMALS)}_eye"
    eye_scale = head_scale * scale_for(eye_name, f"{head_animal}_eye")
    attach(head[:3], eye_name, "eyes", 0, eye_scale)

    if rng.random() < OPTIONAL_CHANCE:
        crest_scale = head_width / bbox_size(load_part("peacock_head"))[0]
        attach(head[:3], "peacock_crest", "horns", 0, crest_scale)
    if rng.random() < OPTIONAL_CHANCE:
        wing_scale = bbox_size(torso_img)[1] / bbox_size(load_part("peacock_torso"))[1]
        attach(torso, "peacock_wing", "wings", 0, wing_scale)

    canvas = Image.new("RGBA", torso_img.size, (0, 0, 0, 0))
    # Draw back-to-front by z
    for _, img, off in sorted(layers, key=lambda l: l[0]):
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(img, off)
        canvas.alpha_composite(layer)
    return canvas, chosen


if __name__ == "__main__":
    # Optional seed to repeat a result: python frankenstein.py 42
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else random.randrange(10**6)
    image, chosen = build(random.Random(seed))
    image.save(OUTPUT)
    print(f"Seed {seed}: {', '.join(chosen)}")
    print(f"Saved {OUTPUT}")