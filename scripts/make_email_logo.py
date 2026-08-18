"""Render the RevCadence wave mark to a PNG for use in email.

Email needs a raster. Gmail strips <svg> entirely and Outlook's Word engine
never supported it, so the mark that ships in the app as an inline SVG path has
to exist as a bitmap somewhere. This renders it from that exact path string, so
the two cannot drift: change the wave in App.jsx and re-run this.

The committed favicons are not usable here — they were exported at a scale that
left the 20-unit stroke far too heavy, and the wave reads as a row of blobs.

Run: python -m scripts.make_email_logo
"""
from pathlib import Path

from PIL import Image, ImageDraw

# The wave, copied verbatim from the <path d="…"> in frontend/src/App.jsx.
WAVE = (
    "M104 235 L121 235 C134 235 134 204 147 204 C160 204 160 235 173 235 "
    "C186 235 186 197 199 197 C212 197 212 235 225 235 C238 235 238 177 251 177 "
    "C264 177 264 235 277 235 C290 235 290 154 303 154 C316 154 316 235 329 235 "
    "C342 235 342 129 355 129 C368 129 368 235 381 235 C394 235 394 101 407 101 "
    "C420 101 420 235 433 235 C446 235 446 72 459 72 C472 72 472 235 485 235 "
    "C498 235 498 42 511 42 C524 42 524 235 537 235 L553 235"
)
STROKE = 20          # strokeWidth in the source SVG's own units
PAD = 14             # breathing room around the mark, same units
SUPERSAMPLE = 4      # drawn big and downscaled — PIL has no antialiased stroke

OUT = Path(__file__).resolve().parents[1] / "app" / "assets" / "revcadence-wave.png"
# --accent from styles.css (light theme). The mark is one flat colour, so this is
# the only place the brand value appears in the mail pipeline.
ACCENT = (79, 70, 229)


def _tokens(d: str):
    out, num = [], ""
    for ch in d:
        if ch in "MLC":
            if num:
                out.append(float(num)); num = ""
            out.append(ch)
        elif ch in " ,":
            if num:
                out.append(float(num)); num = ""
        else:
            num += ch
    if num:
        out.append(float(num))
    return out


def _cubic(p0, p1, p2, p3, steps=24):
    """Flatten one cubic Bézier to points (the curve's t=0 point is the caller's)."""
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        yield (u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
               u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1])


def polyline(d: str) -> list[tuple[float, float]]:
    """The path as a single flat point list — it has no subpaths, by design."""
    tok = _tokens(d)
    pts, cur, i = [], (0.0, 0.0), 0
    while i < len(tok):
        cmd = tok[i]; i += 1
        if cmd == "M":
            cur = (tok[i], tok[i + 1]); i += 2
            pts.append(cur)
        elif cmd == "L":
            cur = (tok[i], tok[i + 1]); i += 2
            pts.append(cur)
        elif cmd == "C":
            c1, c2, end = (tok[i], tok[i + 1]), (tok[i + 2], tok[i + 3]), (tok[i + 4], tok[i + 5])
            i += 6
            pts.extend(_cubic(cur, c1, c2, end))
            cur = end
    return pts


def render(width_px: int = 320) -> Image.Image:
    pts = polyline(WAVE)
    half = STROKE / 2
    x0 = min(p[0] for p in pts) - half - PAD
    y0 = min(p[1] for p in pts) - half - PAD
    x1 = max(p[0] for p in pts) + half + PAD
    y1 = max(p[1] for p in pts) + half + PAD

    scale = (width_px / (x1 - x0)) * SUPERSAMPLE
    w = round((x1 - x0) * scale)
    h = round((y1 - y0) * scale)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    xy = [((x - x0) * scale, (y - y0) * scale) for x, y in pts]
    stroke = max(1, round(STROKE * scale))

    # joint="curve" rounds the joins; PIL has no round *caps*, so the two ends get
    # a circle of their own. Without them the wave stops with a blunt edge that
    # reads as a rendering mistake at small sizes.
    draw.line(xy, fill=ACCENT + (255,), width=stroke, joint="curve")
    for end in (xy[0], xy[-1]):
        r = stroke / 2
        draw.ellipse([end[0] - r, end[1] - r, end[0] + r, end[1] + r], fill=ACCENT + (255,))

    return img.resize((round(w / SUPERSAMPLE), round(h / SUPERSAMPLE)), Image.LANCZOS)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = render()
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({img.width}x{img.height}, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
