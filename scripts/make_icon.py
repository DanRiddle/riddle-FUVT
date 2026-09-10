from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is needed to build the icon:  pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "assets" / "logo-master.png"
ICO = ROOT / "assets" / "Riddle-FUVT.ico"
WEB_LOGO = ROOT / "web" / "logo.png"

SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

SIMPLIFY_BELOW = 32
SIMPLE_CROP = 0.62


def load_master() -> Image.Image:
    if not MASTER.exists():
        sys.exit(f"missing {MASTER.relative_to(ROOT)} - drop the logo there first")
    image = Image.open(MASTER).convert("RGBA")
    box = image.getbbox()
    if box:
        image = image.crop(box)
    side = max(image.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return square


def crop_centre(image: Image.Image, keep: float) -> Image.Image:
    margin = int(image.width * (1 - keep) / 2)
    return image.crop((margin, margin, image.width - margin, image.height - margin))


def render(master: Image.Image, simple: Image.Image, size: int) -> Image.Image:
    source = simple if size < SIMPLIFY_BELOW else master
    return source.resize((size, size), Image.LANCZOS)


def main() -> int:
    master = load_master()
    simple = crop_centre(master, SIMPLE_CROP)
    frames = [render(master, simple, size) for size in SIZES]

    ICO.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(ICO, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"wrote {ICO.relative_to(ROOT)}  ({', '.join(str(s) for s in SIZES)})")

    master.resize((256, 256), Image.LANCZOS).save(WEB_LOGO, format="PNG",
                                                  optimize=True)
    print(f"wrote {WEB_LOGO.relative_to(ROOT)}  (256x256)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
