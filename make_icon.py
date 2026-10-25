#!/usr/bin/env python3
"""Generate icon-512.png — brand §6: eclipse motif on navy
(#0d1b2a), one per-product glyph. Book's glyph is the order
book itself: two columns of bid/ask levels meeting at a spread,
inside the gradient eclipse ring. PIL only; deterministic."""
from PIL import Image, ImageDraw

S = 512
NAVY = (13, 27, 42, 255)
STOPS = [(15, 246, 247), (0, 212, 255), (123, 44, 191)]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def grad(t):
    return lerp(STOPS[0], STOPS[1], t * 2) if t < 0.5 else \
        lerp(STOPS[1], STOPS[2], (t - 0.5) * 2)


def main():
    img = Image.new("RGBA", (S, S), NAVY)
    d = ImageDraw.Draw(img)
    ring = [54, 54, 458, 458]
    for i in range(72):
        t = i / 72
        d.arc(ring, start=i * 5, end=i * 5 + 6, fill=grad(t), width=13)
    d.ellipse([126, 126, 386, 386], fill=NAVY)
    # The book: bid levels (left, cyan) descending toward the
    # spread; ask levels (right, purple) ascending away.
    for i, w in enumerate((120, 96, 74)):
        y = 168 + i * 34
        d.rectangle([150, y, 150 + w, y + 20], fill=grad(0.15 + 0.1 * i))
    for i, w in enumerate((74, 96, 120)):
        y = 288 + i * 34
        d.rectangle([362 - w, y, 362, y + 20], fill=grad(0.7 + 0.1 * i))
    # The spread line.
    d.line([(150, 278), (362, 278)], fill=(254, 254, 254, 255), width=5)
    img.save("icon-512.png")
    print("wrote icon-512.png", img.size, img.mode)


if __name__ == "__main__":
    main()
