#!/usr/bin/env python3
"""Generatore reel 9:16 muti, stesso linguaggio grafico dei post.

Uso:
    python3 templates/genera_reel.py reel.json

Il JSON e' una lista di reel: {"slug", "categoria", "variante", "cards":[...]}
Ogni card: {"dur": 2.4, "lines": [["testo", "stile"], ...]}
Stili: hook | big | mid | small | en
L'audio va aggiunto in app (i reel via API sono muti).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genera_grafiche as G                                   # noqa: E402
from PIL import Image, ImageDraw                              # noqa: E402

W, H = 1080, 1920
FPS = 30
XFADE = 0.30
MARGIN = 96
BOTTOM_SAFE = 340          # zona coperta dalla UI di Instagram
ZOOM_STEP = 0.0009         # zoom lento, ~6% su una card da 2.4s

# stile -> (font, dimensione massima, chiave colore)
STYLES = {
    "hook":  (G.FONT_TITLE,   152, "text"),
    "big":   (G.FONT_TITLE,   116, "text"),
    "mid":   (G.FONT_BOLD,     60, "accent2"),
    "small": (G.FONT_REGULAR,  46, "accent1"),
    "en":    (G.FONT_MEDIUM,   50, "accent1"),
}
GAP = 34


def render_card(colors, lines):
    base = Image.new("RGBA", (W, H), colors["bg"])
    base = G.draw_watermark(base, colors)
    draw = ImageDraw.Draw(base)

    colmap = {
        "text": colors["text"],
        "accent1": G.readable_accent("accent1", colors),
        "accent2": G.readable_accent("accent2", colors),
    }
    content_w = W - 2 * MARGIN

    items = []
    for text, style in lines:
        fname, size, ckey = STYLES[style]
        while size > 26 and G.text_width(G.get_font(fname, size), text) > content_w:
            size -= 3
        font = G.get_font(fname, size)
        items.append({"font": font, "text": text,
                      "color": colmap[ckey], "h": G.line_height(font)})

    stack = sum(i["h"] for i in items) + GAP * (len(items) - 1)
    top = MARGIN + 140
    bottom = H - BOTTOM_SAFE - 120
    y = top + max(0, (bottom - top - stack) // 2)

    for it in items:
        draw.text((W // 2, y), it["text"], font=it["font"],
                  fill=it["color"], anchor="ma")
        y += it["h"] + GAP

    # firma: handle in basso a sinistra, logo in basso a destra (come i post)
    footer_font = G.get_font(G.FONT_MEDIUM, 32)
    fy = H - BOTTOM_SAFE + 40
    draw.text((MARGIN, fy), G.OFFICIAL_HANDLE, font=footer_font,
              fill=colmap["accent1"], anchor="la")
    logo = G.load_logo(96)
    base.paste(logo, (W - MARGIN - logo.width, fy - 24), logo)

    return base.convert("RGB")


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out.split(",")[0])


def build_video(cards, out_path, workdir):
    """Il sandbox ha ~1 GB di RAM e 1 core: montare tutto in un filter_complex
    unico lo fa fuori a memoria. Quindi un segmento per card, poi dissolvenze
    a coppie (mai piu' di due stream aperti insieme).

    Attenzione: 'fps' va messo PRIMA di zoompan, altrimenti zoompan lavora ai
    suoi 25 fps di default e il segmento esce piu' corto del richiesto, con gli
    offset delle dissolvenze che finiscono oltre la fine della clip."""
    def run(args):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args, check=True)

    tmp, segs = [], []
    for i, card in enumerate(cards):
        png = os.path.join(workdir, f"card_{i:02d}.png")
        seg = os.path.join(workdir, f"seg_{i:02d}.mp4")
        card["img"].save(png, "PNG")
        vf = (f"fps={FPS},scale=1620:2880,"
              f"zoompan=z='min(1+{ZOOM_STEP}*on,1.09)':d=1:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"s={W}x{H}:fps={FPS},setsar=1")
        run(["-loop", "1", "-t", str(card["dur"]), "-i", png, "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
             "-pix_fmt", "yuv420p", "-r", str(FPS), seg])
        segs.append(seg)
        tmp += [png, seg]

    # offset calcolati sulle durate REALI dei segmenti, non su quelle nominali
    cur, acc = segs[0], probe_duration(segs[0])
    for i in range(1, len(segs)):
        offset = round(acc - XFADE, 3)
        merged = os.path.join(workdir, f"merge_{i:02d}.mp4")
        run(["-i", cur, "-i", segs[i], "-filter_complex",
             f"[0:v][1:v]xfade=transition=fade:duration={XFADE}:"
             f"offset={offset}[v]",
             "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), merged])
        acc = round(acc + probe_duration(segs[i]) - XFADE, 3)
        cur = merged
        tmp.append(merged)

    # traccia audio muta: i reel via API sono senza suono, l'audio di tendenza
    # si aggiunge in app. Copia il video, costa quasi nulla.
    run(["-i", cur, "-f", "lavfi", "-i",
         "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest",
         "-movflags", "+faststart", out_path])

    real = probe_duration(out_path)
    if abs(real - acc) > 0.2:
        raise RuntimeError(f"durata anomala: attesa {acc}s, ottenuta {real}s")

    for f in tmp:
        if os.path.exists(f):
            os.remove(f)
    return real


def resolve_colors(palette, categoria, variante):
    colors = palette[categoria]
    if variante == "alt" and isinstance(colors.get("alt"), dict):
        colors = colors["alt"]
    return colors


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    palette = G.load_palette()
    os.makedirs(G.OUTPUT_DIR, exist_ok=True)

    for reel in spec:
        cards = []
        for c in reel["cards"]:
            # ogni card puo' sovrascrivere categoria/variante del reel: serve
            # alle rassegne, dove cambiare sfondo a ogni giornata da ritmo
            # visivo e aiuta a trattenere lo spettatore.
            colors = resolve_colors(
                palette,
                c.get("categoria", reel["categoria"]),
                c.get("variante", reel.get("variante")),
            )
            cards.append({"img": render_card(colors, c["lines"]),
                          "dur": c["dur"]})
        out = os.path.join(G.OUTPUT_DIR, f'{reel["slug"]}_reel.mp4')
        dur = build_video(cards, out, G.OUTPUT_DIR)
        print(f"OK  {out}  ({dur}s, {len(cards)} card)")


if __name__ == "__main__":
    main()
