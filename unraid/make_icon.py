"""Generate the SortDVR app icon (unraid/icon.png).

Concept: one recording (the red 'record' dot at the base) fans out into three
routed streams — TV (blue), Movie (amber), Sport (green) — the app's whole job
in one glyph. Run: python unraid/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

S = 512
BG_TOP = (30, 41, 59)      # slate-800
BG_BOT = (15, 23, 42)      # slate-900
TRUNK = (226, 232, 240)    # slate-200
RECORD = (239, 68, 68)     # red-500
TV = (59, 130, 246)        # blue-500
MOVIE = (245, 158, 11)     # amber-500
SPORT = (34, 197, 94)      # green-500
WHITE = (248, 250, 252)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# vertical gradient background on a rounded square
grad = Image.new("RGB", (1, S))
for y in range(S):
    t = y / S
    grad.putpixel((0, y), tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3)))
grad = grad.resize((S, S))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=96, fill=255)
img.paste(grad, (0, 0), mask)

HUB = (256, 296)
RECORD_PT = (256, 436)
ENDS = {TV: (118, 118), MOVIE: (256, 92), SPORT: (394, 118)}


def stroke(p0, p1, color, w):
    d.line([p0, p1], fill=color, width=w)
    for p in (p0, p1):  # round the caps
        d.ellipse([p[0] - w // 2, p[1] - w // 2, p[0] + w // 2, p[1] + w // 2], fill=color)


# trunk from the hub down to the record dot
stroke(HUB, RECORD_PT, TRUNK, 30)
# three routed branches
for color, end in ENDS.items():
    stroke(HUB, end, color, 30)

# hub knot + record dot
d.ellipse([HUB[0] - 20, HUB[1] - 20, HUB[0] + 20, HUB[1] + 20], fill=TRUNK)
d.ellipse([RECORD_PT[0] - 40, RECORD_PT[1] - 40, RECORD_PT[0] + 40, RECORD_PT[1] + 40], fill=RECORD)

# end nodes with a simple white glyph each
for color, (x, y) in ENDS.items():
    d.ellipse([x - 44, y - 44, x + 44, y + 44], fill=color)
    if color == TV:            # screen
        d.rounded_rectangle([x - 22, y - 15, x + 22, y + 15], radius=6, fill=WHITE)
        d.rectangle([x - 8, y + 15, x + 8, y + 22], fill=WHITE)
    elif color == MOVIE:       # play triangle
        d.polygon([(x - 15, y - 20), (x - 15, y + 20), (x + 22, y)], fill=WHITE)
    else:                      # sport ball (ring)
        d.ellipse([x - 22, y - 22, x + 22, y + 22], outline=WHITE, width=7)
        d.line([(x - 22, y), (x + 22, y)], fill=WHITE, width=5)

out = Path(__file__).parent / "icon.png"
img.save(out)
img.resize((256, 256), Image.LANCZOS).save(out)  # ship a crisp 256px icon
print("wrote", out)
