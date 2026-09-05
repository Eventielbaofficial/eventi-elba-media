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

# Layout "agenda": e' quello del reel pinnato "La settimana all'Elba".
# Testo allineato a SINISTRA, blocco ancorato in ALTO, sfondo unico, titolo del
# giorno seguito da un trattino accento, ogni evento su due righe (nome in
# grassetto + luogo/orario in accento). Nessun logo in basso a destra: solo
# l'handle centrato, com'e' nel pinnato.
AGENDA_STYLES = {
    "kicker": (G.FONT_BOLD,    36, "accent1", 16),
    "title":  (G.FONT_TITLE,  130, "text",     6),
    "day":    (G.FONT_TITLE,  104, "text",    22),
    "event":  (G.FONT_BOLD,    54, "text",     8),
    "meta":   (G.FONT_REGULAR, 40, "accent2", 34),
    "sub":    (G.FONT_REGULAR, 40, "text",    28),
    "gold":   (G.FONT_BOLD,    42, "gold",    10),
    "handle": (G.FONT_BOLD,    42, "sky",     10),
    "cta":    (G.FONT_TITLE,  104, "text",    16),
}
RULE_W, RULE_H, RULE_GAP = 120, 7, 34     # trattino sotto il titolo del giorno
AGENDA_TOP = 260                           # bordo alto della zona utile


PILL_FONT_SIZE = 36
PILL_PAD_X, PILL_PAD_Y = 40, 20
PILL_GAP = 52          # respiro tra etichetta e blocco testo


def agenda_layout(lines, scale):
    """(altezza_totale, voci) di una card agenda alla scala data."""
    content_w = W - 2 * MARGIN
    items, total = [], 0
    for text, style in lines:
        if style == "rule":
            items.append(("rule", None, None, RULE_H, RULE_GAP))
            total += RULE_H + RULE_GAP
            continue
        fname, size, ckey, after = AGENDA_STYLES[style]
        size = max(20, int(size * scale))
        after = int(after * scale)
        while size > 20 and G.text_width(G.get_font(fname, size),
                                         text) > content_w:
            size -= 2
        font = G.get_font(fname, size)
        lh = G.line_height(font)
        items.append(("text", text, (font, ckey), lh, after))
        total += lh + after
    return total, items


def fit_agenda_scale(cards_lines):
    """UNA scala per tutte le card agenda del reel: la piu' piccola che serve.

    Prima ogni card si rimpiccioliva per conto suo, quindi dentro lo stesso
    reel il titolo di una giornata affollata usciva piu' piccolo di quello di
    una giornata con due eventi. Deciso il 5/09: meglio tutte uguali, anche se
    vuol dire che il reel intero scende alla misura della card piu' piena.
    """
    region_h = (H - BOTTOM_SAFE) - AGENDA_TOP
    worst = 1.0
    for lines in cards_lines:
        scale = 1.0
        total, _ = agenda_layout(lines, scale)
        while total > region_h and scale > 0.45:
            scale -= 0.04
            total, _ = agenda_layout(lines, scale)
        worst = min(worst, scale)
    return worst


def fit_center_sizes(cards_lines):
    """UNA misura per ogni stile su tutte le card 'center' del reel.

    Stessa ragione di fit_agenda_scale: il titolo di una card non deve uscire
    piu' piccolo di quello di un'altra card dello stesso reel. Il minimo si
    prende per stile, non sul reel intero: un 'big' lungo non deve trascinare
    giu' anche i 'small', che non c'entrano.
    """
    content_w = W - 2 * MARGIN
    sizes = {}
    for lines in cards_lines:
        for text, style in lines:
            fname, size, _ = STYLES[style]
            while size > 26 and G.text_width(G.get_font(fname, size),
                                             text) > content_w:
                size -= 3
            sizes[style] = min(sizes.get(style, size), size)
    return sizes


def render_agenda_card(colors, lines, extra, scale=1.0):
    """Card 'agenda' delle rassegne: testo CENTRATO, blocco centrato in verticale.

    Prima era a sinistra e ancorato in alto. Cambiato il 2/09 su richiesta
    dell'utente per uniformarla agli altri reel e ai post. Le scritte sono
    cresciute, quindi c'e' un guard: se la pila non ci sta in altezza si
    rimpicciolisce tutto in blocco invece di sforare.
    """
    base = Image.new("RGBA", (W, H), colors["bg"])
    base = G.draw_watermark(base, colors)
    draw = ImageDraw.Draw(base)

    colmap = dict(extra)
    colmap.update({
        "text": colors["text"],
        "accent1": G.readable_accent("accent1", colors),
        "accent2": G.readable_accent("accent2", colors),
    })
    content_w = W - 2 * MARGIN
    region_top = AGENDA_TOP
    region_h = (H - BOTTOM_SAFE) - region_top

    def layout(scale):
        return agenda_layout(lines, scale)

    # La scala arriva gia' decisa da fit_agenda_scale(), che la calcola UNA
    # volta su tutte le card del reel e applica a tutte la piu' piccola: cosi'
    # il titolo di sabato non esce piu' piccolo di quello di domenica dentro lo
    # stesso reel. Il ciclo qui sotto resta come rete di sicurezza.
    total, items = layout(scale)
    while total > region_h and scale > 0.45:
        scale -= 0.04
        total, items = layout(scale)

    cx = W // 2
    y = region_top + max(0, (region_h - total) // 2)
    for kind, text, meta, h, after in items:
        if kind == "rule":
            draw.rounded_rectangle(
                [cx - RULE_W // 2, y, cx + RULE_W // 2, y + RULE_H],
                radius=RULE_H // 2, fill=colmap["accent2"])
            y += h + after
            continue
        font, ckey = meta
        draw.text((cx, y), text, font=font, fill=colmap[ckey], anchor="ma")
        y += h + after

    # firma centrata in basso, senza logo
    footer_font = G.get_font(G.FONT_MEDIUM, 32)
    draw.text((cx, H - BOTTOM_SAFE + 60), G.OFFICIAL_HANDLE,
              font=footer_font, fill=colmap["accent1"], anchor="ma")

    return base.convert("RGB")


def render_card(colors, lines, label=None, style_sizes=None):
    """label: testo dell'etichetta (pill). None = nessuna etichetta, utile
    sulle card di servizio (riga in inglese, CTA) che non sono eventi.

    style_sizes: misure gia' decise da fit_center_sizes() su TUTTE le card del
    reel, cosi' lo stesso stile ha la stessa misura ovunque."""
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
        if style_sizes and style in style_sizes:
            size = style_sizes[style]
        # rete di sicurezza: se anche la misura comune sfora, questa riga cede
        while size > 26 and G.text_width(G.get_font(fname, size), text) > content_w:
            size -= 3
        font = G.get_font(fname, size)
        items.append({"font": font, "text": text,
                      "color": colmap[ckey], "h": G.line_height(font)})

    stack = sum(i["h"] for i in items) + GAP * (len(items) - 1)

    pill = None
    if label:
        pf = G.get_font(G.FONT_BOLD, PILL_FONT_SIZE)
        text = label.upper()
        pill = {"font": pf, "text": text,
                "w": G.text_width(pf, text) + 2 * PILL_PAD_X,
                "h": G.line_height(pf) + 2 * PILL_PAD_Y}
        stack += pill["h"] + PILL_GAP

    top = MARGIN + 140
    bottom = H - BOTTOM_SAFE - 120
    y = top + max(0, (bottom - top - stack) // 2)

    if pill:
        x0 = W // 2 - pill["w"] // 2
        draw.rounded_rectangle(
            [x0, y, x0 + pill["w"], y + pill["h"]],
            radius=pill["h"] // 2, fill=colors["pill_bg"])
        draw.text((W // 2, y + pill["h"] // 2), pill["text"],
                  font=pill["font"], fill=colors["pill_text"], anchor="mm")
        y += pill["h"] + PILL_GAP

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

    # Gli arancioni dei reel uscivano diversi da quelli dei post (segnalato
    # dall'utente il 5/09). Misurato: lo sfondo #E86A34 del post diventa
    # #E66933 nel video, e il crema #F4E4C1 deriva ancora di piu' lungo la
    # catena di merge. La causa e' che i segmenti uscivano SENZA nessun tag di
    # colore (color_space/primaries/transfer = unknown): Instagram e iOS
    # devono tirare a indovinare la matrice in decodifica, e su un fondo
    # saturo si vede. Qui la matrice si dichiara esplicitamente, uguale a
    # ogni passaggio, cosi' i re-encode della catena non spostano piu' niente.
    COLOR_IN = "scale=out_color_matrix=bt709:out_range=tv"
    COLOR_OUT = ["-colorspace", "bt709", "-color_primaries", "bt709",
                 "-color_trc", "bt709", "-color_range", "tv"]

    tmp, segs = [], []
    for i, card in enumerate(cards):
        png = os.path.join(workdir, f"card_{i:02d}.png")
        seg = os.path.join(workdir, f"seg_{i:02d}.mp4")
        card["img"].save(png, "PNG")
        vf = (f"fps={FPS},scale=1620:2880,"
              f"zoompan=z='min(1+{ZOOM_STEP}*on,1.09)':d=1:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"s={W}x{H}:fps={FPS},setsar=1,{COLOR_IN}")
        run(["-loop", "1", "-t", str(card["dur"]), "-i", png, "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
             "-pix_fmt", "yuv420p", "-r", str(FPS)] + COLOR_OUT + [seg])
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
             "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS)]
            + COLOR_OUT + [merged])
        acc = round(acc + probe_duration(segs[i]) - XFADE, 3)
        cur = merged
        tmp.append(merged)

    # traccia audio muta: i reel via API sono senza suono, l'audio di tendenza
    # si aggiunge in app. Copia il video, costa quasi nulla.
    run(["-i", cur, "-f", "lavfi", "-i",
         "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest",
         "-movflags", "+faststart"] + COLOR_OUT + [out_path])

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

    # colori aggiuntivi presi comunque DALLA palette (mai inventati): l'oro e
    # l'azzurro vivono sotto altre categorie ma servono trasversalmente.
    extra = {"gold": palette["live_music"]["accent2"],
             "sky": palette["live_music"]["accent1"]}

    for reel in spec:
        cards = []
        # pre-passata: le misure si decidono una volta su TUTTO il reel, non
        # card per card, altrimenti dentro lo stesso reel il titolo balla.
        def kind_of(c):
            return c.get("layout", reel.get("layout", "center"))
        agenda_scale = fit_agenda_scale(
            [c["lines"] for c in reel["cards"] if kind_of(c) == "agenda"])
        center_sizes = fit_center_sizes(
            [c["lines"] for c in reel["cards"] if kind_of(c) != "agenda"])
        for c in reel["cards"]:
            # ogni card puo' sovrascrivere categoria/variante del reel: serve
            # alle rassegne, dove cambiare sfondo a ogni giornata da ritmo
            # visivo e aiuta a trattenere lo spettatore.
            colors = resolve_colors(
                palette,
                c.get("categoria", reel["categoria"]),
                c.get("variante", reel.get("variante")),
            )
            layout = kind_of(c)
            if layout == "agenda":
                img = render_agenda_card(colors, c["lines"], extra,
                                         scale=agenda_scale)
            else:
                # etichetta: per default quella della categoria della card
                # (LIVE MUSIC / SERATA / APERITIVO / DJ SET), sovrascrivibile con
                # "label", o disattivabile con "label": null sulle card di servizio
                label = c["label"] if "label" in c else colors["label"]
                img = render_card(colors, c["lines"], label,
                                  style_sizes=center_sizes)
            cards.append({"img": img, "dur": c["dur"]})
        out = os.path.join(G.OUTPUT_DIR, f'{reel["slug"]}_reel.mp4')
        dur = build_video(cards, out, G.OUTPUT_DIR)
        print(f"OK  {out}  ({dur}s, {len(cards)} card)")


if __name__ == "__main__":
    main()
