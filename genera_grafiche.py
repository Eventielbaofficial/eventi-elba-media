#!/usr/bin/env python3
"""
Generatore grafiche eventi (post 4:5 + story 9:16 + caption).

Uso:
    python3 templates/genera_grafiche.py eventi.json

Regole:
- I colori si leggono SOLO da config/palette.json (nessun colore hardcodato).
- Il logo si legge SOLO da assets/logo.png.
- I font si leggono SOLO da assets/fonts/.
- Layout a fasce verticali: ogni blocco vive in una banda propria,
  spaziatura generosa, nessun testo sovrapposto.
- Elementi decorativi coerenti con la categoria, sotto il testo, sottili.
- Nessun tag inventato: solo quelli presenti nel JSON.
"""

import colorsys
import json
import math
import os
import random
import re
import sys

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# --------------------------------------------------------------------------- #
# Percorsi
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PALETTE_PATH = os.path.join(ROOT, "config", "palette.json")
LOGO_PATH = os.path.join(ROOT, "assets", "logo.png")
LOGO_MARK_PATH = os.path.join(ROOT, "assets", "logo_mark.png")
FONTS_DIR = os.path.join(ROOT, "assets", "fonts")
OUTPUT_DIR = os.path.join(ROOT, "output")

FONT_TITLE = "BigShoulders-Bold.ttf"
FONT_BOLD = "Poppins-Bold.ttf"
FONT_MEDIUM = "Poppins-Medium.ttf"
FONT_REGULAR = "Poppins-Regular.ttf"

OFFICIAL_HANDLE = "@eventi.elba.official"

# Decorazioni geometriche di categoria (onde/raggi/linee/stelle).
# Disattivate: la filigrana logo-mark fa da unico elemento di sfondo.
GEOMETRIC_DECOR = False
DECOR_ALPHA = int(255 * 0.13)

# Filigrana: logo-mark line-art grande al centro, SEMPRE piu' chiara dello
# sfondo. Usa assets/logo_mark.png se presente, altrimenti assets/logo.png.
WATERMARK = True
WATERMARK_SCALE = 1.20        # grande: sfora i bordi per un effetto ampio
# Filigrana allineata come visibilita' tra fondo chiaro e scuro; sul fondo
# scuro schiarita di piu' cosi' e' nettamente piu' chiara dello sfondo.
WATERMARK_OPACITY_DARK = 0.58
WATERMARK_OPACITY_LIGHT = 0.28
WATERMARK_LIGHTEN_DARK = 0.70   # schiarita (HSL) su fondo scuro
WATERMARK_LIGHTEN_LIGHT = 0.38  # schiarita (HSL) su fondo chiaro
WATERMARK_THICKEN = 7         # ispessimento linee (dilatazione, px dispari)
WATERMARK_SHIFT = 0.10        # spostamento logo in basso a dx (1/10 larghezza)

# Contrasto minimo di un accento sullo sfondo prima di usare l'altro accento.
ACCENT_MIN_CONTRAST = 1.8

# Dinamicità feed: sugli eventi in posizione dispari scambia accent1<->accent2
# (resta tutto dentro palette.json, contrasto sempre garantito sul bg).
ALTERNATE_INVERT = True

# Emoji + vibe per categoria (usati SOLO nella caption di testo)
CATEGORY_META = {
    "live_music": {"emoji": "🎶", "emoji2": "🎤",
                   "vibe": "la grande musica dal vivo sotto le stelle"},
    "dj_set_serata": {"emoji": "🎧", "emoji2": "🌙",
                      "vibe": "il ritmo che non si ferma fino a tardi"},
    "aperitivo": {"emoji": "🍹", "emoji2": "🌅",
                  "vibe": "il tramonto più bello tra drink e buona musica"},
    "festa_special": {"emoji": "🎉", "emoji2": "✨",
                      "vibe": "la festa che stavi aspettando"},
    "_default": {"emoji": "🎫", "emoji2": "✨",
                 "vibe": "una serata da vivere insieme"},
}

# --------------------------------------------------------------------------- #
# Formati
# --------------------------------------------------------------------------- #
FORMATS = {
    "post": {
        "size": (1080, 1350),
        "align": "center",
        "margin": 90,
        "logo_px": 88,
        "logo_pad": 40,        # margine di rispetto del logo dai bordi
        "gap": 52,
        "bottom_safe": 90,     # baseline footer/logo dal fondo
        "sizes": {
            "title": 88, "pill": 30, "data": 46,
            "luogo": 40, "contesto": 34, "footer": 28,
        },
    },
    "story": {
        "size": (1080, 1920),
        "align": "center",
        "margin": 90,
        "logo_px": 116,
        "logo_pad": 40,
        "gap": 60,
        "bottom_safe": 250,    # safe zone sticker IG dal fondo
        "sizes": {
            "title": 96, "pill": 32, "data": 50,
            "luogo": 44, "contesto": 36, "footer": 30,
        },
    },
}


# --------------------------------------------------------------------------- #
# Utility risorse / colori
# --------------------------------------------------------------------------- #
def load_palette():
    with open(PALETTE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


_font_cache = {}


def get_font(filename, size):
    key = (filename, size)
    if key not in _font_cache:
        path = os.path.join(FONTS_DIR, filename)
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def load_logo(px):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    ratio = logo.height / logo.width
    return logo.resize((px, int(px * ratio)), Image.LANCZOS)


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgba(hex_value, alpha):
    return hex_to_rgb(hex_value) + (alpha,)


def luminance(hex_value):
    r, g, b = hex_to_rgb(hex_value)
    return 0.299 * r + 0.587 * g + 0.114 * b


def adjust_color(hex_value, amount):
    """amount in [-1,1]: >0 schiarisce verso il bianco, <0 scurisce."""
    r, g, b = hex_to_rgb(hex_value)
    if amount >= 0:
        return (int(r + (255 - r) * amount),
                int(g + (255 - g) * amount),
                int(b + (255 - b) * amount))
    a = -amount
    return (int(r * (1 - a)), int(g * (1 - a)), int(b * (1 - a)))


def _rel_luminance(hex_value):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_to_rgb(hex_value)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(hex_a, hex_b):
    la, lb = _rel_luminance(hex_a), _rel_luminance(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable_accent(primary_key, colors):
    """Ritorna l'accento indicato se ha contrasto sufficiente sullo sfondo,
    altrimenti l'altro accento (solo colori della palette). Serve a non far
    'sparire' es. l'oro su fondo chiaro."""
    prim = colors[primary_key]
    other_key = "accent1" if primary_key == "accent2" else "accent2"
    other = colors[other_key]
    if contrast_ratio(prim, colors["bg"]) >= ACCENT_MIN_CONTRAST:
        return prim
    if contrast_ratio(other, colors["bg"]) > contrast_ratio(prim, colors["bg"]):
        return other
    return prim


def lighten_same_hue(hex_value, amount):
    """Schiarisce mantenendo la stessa tinta: alza la luminosita' in HSL
    (verso 1) di una frazione, lasciando invariati tonalita' e saturazione."""
    r, g, b = (c / 255 for c in hex_to_rgb(hex_value))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l + (1 - l) * amount
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    return slug or "evento"


# --------------------------------------------------------------------------- #
# Misure testo
# --------------------------------------------------------------------------- #
def line_height(font):
    ascent, descent = font.getmetrics()
    return ascent + descent


def text_width(font, text):
    return int(font.getlength(text))


def wrap_lines(font, text, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if text_width(font, trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_title(text, base_size, max_width, min_size=48):
    size = base_size
    while size > min_size:
        font = get_font(FONT_TITLE, size)
        lines = wrap_lines(font, text, max_width)
        if all(text_width(font, ln) <= max_width for ln in lines):
            return font, lines
        size -= 4
    font = get_font(FONT_TITLE, min_size)
    return font, wrap_lines(font, text, max_width)


# --------------------------------------------------------------------------- #
# Elementi decorativi di sfondo (coerenti con la categoria, sotto al testo)
# --------------------------------------------------------------------------- #
def decor_live_music(draw, W, H, color):
    """Cerchi concentrici / onde sonore nell'angolo basso-destro."""
    cx, cy = W, H
    for r in range(150, 1050, 135):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     outline=color, width=14)


def decor_aperitivo(draw, W, H, color):
    """Raggi solari semicircolari nell'angolo alto-destro."""
    cx, cy = W, 0
    length = 1500
    for deg in range(94, 180, 7):
        theta = math.radians(deg)
        x = cx + length * math.cos(theta)
        y = cy + length * math.sin(theta)
        draw.line([cx, cy, x, y], fill=color, width=16)


def decor_dj_set(draw, W, H, color):
    """Linee diagonali parallele."""
    spacing = 150
    for x in range(-H, W + H, spacing):
        draw.line([x, H, x + H, 0], fill=color, width=9)


def decor_festa(draw, W, H, color):
    """Stelle / punti sparsi."""
    rnd = random.Random(7)
    for _ in range(46):
        x = rnd.randint(40, W - 40)
        y = rnd.randint(40, H - 40)
        r = rnd.randint(4, 16)
        if rnd.random() < 0.4:                       # sparkle a 4 punte
            draw.line([x - r, y, x + r, y], fill=color, width=5)
            draw.line([x, y - r, x, y + r], fill=color, width=5)
        else:                                        # punto
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


DECOR = {
    "live_music": (decor_live_music, "accent1"),
    "aperitivo": (decor_aperitivo, "accent2"),
    "dj_set_serata": (decor_dj_set, "accent1"),
    "festa_special": (decor_festa, "accent1"),
}


def draw_decor(base, categoria, colors):
    """Disegna la decorazione su un layer trasparente e la compone sotto."""
    if categoria not in DECOR:
        return base
    func, color_key = DECOR[categoria]
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    func(odraw, base.width, base.height, rgba(colors[color_key], DECOR_ALPHA))
    return Image.alpha_composite(base, overlay)


def _watermark_alpha(mark):
    """Ricava la maschera alpha della filigrana. Se il PNG ha gia' un alpha
    utile lo usa; se e' line-art su fondo bianco (senza alpha), deriva la
    maschera dalla scurezza: linee scure -> opache, bianco -> trasparente."""
    if mark.mode in ("RGBA", "LA"):
        alpha = mark.getchannel("A")
        if alpha.getextrema() != (255, 255):     # alpha significativo
            return alpha
    gray = ImageOps.grayscale(mark)
    return gray.point(lambda v: 255 - v)          # inverti: nero -> opaco


def draw_watermark(base, colors):
    """Logo-mark line-art centrato come filigrana, SEMPRE piu' chiara dello
    sfondo, con linee ispessite."""
    W, H = base.size
    is_dark = luminance(colors["bg"]) < 128
    lighten = WATERMARK_LIGHTEN_DARK if is_dark else WATERMARK_LIGHTEN_LIGHT
    opacity = WATERMARK_OPACITY_DARK if is_dark else WATERMARK_OPACITY_LIGHT
    tint = lighten_same_hue(colors["bg"], lighten)           # stessa tinta

    path = LOGO_MARK_PATH if os.path.isfile(LOGO_MARK_PATH) else LOGO_PATH
    mark = Image.open(path)
    alpha = _watermark_alpha(mark)

    target_w = int(W * WATERMARK_SCALE)
    ratio = alpha.height / alpha.width
    size = (target_w, int(target_w * ratio))
    alpha = alpha.resize(size, Image.LANCZOS)

    if WATERMARK_THICKEN and WATERMARK_THICKEN >= 3:       # linee piu' spesse
        alpha = alpha.filter(ImageFilter.MaxFilter(WATERMARK_THICKEN))
    alpha = alpha.point(lambda v: int(v * opacity))

    tinted = Image.new("RGBA", size, tint + (0,))
    tinted.putalpha(alpha)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay.paste(tinted, ((W - size[0]) // 2, (H - size[1]) // 2), tinted)
    return Image.alpha_composite(base, overlay)


# --------------------------------------------------------------------------- #
# Costruzione blocchi di contenuto (fasce verticali)
# --------------------------------------------------------------------------- #
def build_elements(evento, colors, fmt, content_width):
    sizes = fmt["sizes"]
    elements = []
    # accenti garantiti leggibili sullo sfondo (evita l'oro che sparisce)
    acc2 = readable_accent("accent2", colors)
    acc1 = readable_accent("accent1", colors)

    # pill categoria
    pill_font = get_font(FONT_BOLD, sizes["pill"])
    pill_label = colors["label"].upper()
    pill_text_h = line_height(pill_font)
    pill_pad_x, pill_pad_y = 34, 18
    pill_w = text_width(pill_font, pill_label) + 2 * pill_pad_x
    pill_h = pill_text_h + 2 * pill_pad_y
    elements.append({
        "type": "pill", "height": pill_h, "width": pill_w,
        "font": pill_font, "text": pill_label,
    })

    # titolo (+ eventuale sottotitolo)
    title_font, title_lines = fit_title(
        evento["nome"].upper(), sizes["title"], content_width
    )
    if evento.get("sottotitolo"):
        title_lines = title_lines + [evento["sottotitolo"].upper()]
    line_gap = 1.06
    tlh = line_height(title_font)
    title_h = int(len(title_lines) * tlh * line_gap)
    elements.append({
        "type": "title", "height": title_h,
        "font": title_font, "lines": title_lines,
        "line_h": tlh, "line_gap": line_gap,
    })

    # separatore
    elements.append({"type": "separator", "height": 6, "width": 140,
                     "color": acc2})

    # data + ora
    data_font = get_font(FONT_BOLD, sizes["data"])
    data_text = f'{evento["data"]}   {evento["ora"]}'.strip()
    elements.append({
        "type": "line", "height": line_height(data_font),
        "font": data_font, "text": data_text, "color": acc2,
    })

    # luogo: nome locale (prominente) + paese (secondario), oppure solo paese
    luogo_font = get_font(FONT_MEDIUM, sizes["luogo"])
    locale = (evento.get("locale") or "").strip()
    if locale:
        town_font = get_font(FONT_REGULAR, sizes["contesto"])
        inner = 12
        elements.append({
            "type": "location", "inner": inner,
            "height": line_height(luogo_font) + inner + line_height(town_font),
            "main": {"text": locale, "font": luogo_font,
                     "color": colors["text"]},
            "sub": {"text": evento["luogo"], "font": town_font,
                    "color": acc1},
        })
    else:
        elements.append({
            "type": "line", "height": line_height(luogo_font),
            "font": luogo_font, "text": evento["luogo"],
            "color": colors["text"],
        })

    # contesto
    if evento.get("contesto"):
        ctx_font = get_font(FONT_REGULAR, sizes["contesto"])
        elements.append({
            "type": "line", "height": line_height(ctx_font),
            "font": ctx_font, "text": evento["contesto"],
            "color": acc1,
        })

    return elements


# --------------------------------------------------------------------------- #
# Rendering blocchi
# --------------------------------------------------------------------------- #
def draw_elements(draw, elements, start_y, fmt, colors, content_left,
                  content_width):
    align = fmt["align"]
    gap = fmt["gap"]
    center_x = content_left + content_width // 2
    y = start_y

    anchor_x = center_x if align == "center" else content_left
    line_anchor = "ma" if align == "center" else "la"

    for el in elements:
        if el["type"] == "pill":
            x0 = (center_x - el["width"] // 2) if align == "center" \
                else content_left
            x1 = x0 + el["width"]
            draw.rounded_rectangle(
                [x0, y, x1, y + el["height"]], radius=el["height"] // 2,
                fill=colors["pill_bg"],
            )
            draw.text((x0 + el["width"] // 2, y + el["height"] // 2),
                      el["text"], font=el["font"], fill=colors["pill_text"],
                      anchor="mm")

        elif el["type"] == "title":
            ty = y
            step = int(el["line_h"] * el["line_gap"])
            for ln in el["lines"]:
                draw.text((anchor_x, ty), ln, font=el["font"],
                          fill=colors["text"], anchor=line_anchor)
                ty += step

        elif el["type"] == "separator":
            x0 = (center_x - el["width"] // 2) if align == "center" \
                else content_left
            draw.rounded_rectangle(
                [x0, y, x0 + el["width"], y + el["height"]],
                radius=el["height"] // 2,
                fill=el.get("color", colors["accent2"]),
            )

        elif el["type"] == "location":
            m, s = el["main"], el["sub"]
            draw.text((anchor_x, y), m["text"], font=m["font"],
                      fill=m["color"], anchor=line_anchor)
            sy = y + line_height(m["font"]) + el["inner"]
            draw.text((anchor_x, sy), s["text"], font=s["font"],
                      fill=s["color"], anchor=line_anchor)

        elif el["type"] == "line":
            draw.text((anchor_x, y), el["text"], font=el["font"],
                      fill=el["color"], anchor=line_anchor)

        y += el["height"] + gap

    return y


def draw_footer(draw, evento, fmt, colors, content_left):
    """@eventi.elba.official sempre in basso a sinistra; handle_locale sopra
    se presente. Ritorna la y piu' alta occupata dal footer."""
    footer_font = get_font(FONT_MEDIUM, fmt["sizes"]["footer"])
    fh = line_height(footer_font)
    W, H = fmt["size"]

    official_top = H - fmt["bottom_safe"] - fh
    draw.text((content_left, official_top), OFFICIAL_HANDLE, font=footer_font,
              fill=colors["accent1"], anchor="la")

    top = official_top
    handle = (evento.get("handle_locale") or "").strip()
    if handle:
        handle_top = official_top - int(fh * 1.25)
        draw.text((content_left, handle_top), handle, font=footer_font,
                  fill=colors["accent1"], anchor="la")
        top = handle_top

    return top


# --------------------------------------------------------------------------- #
# Render immagine
# --------------------------------------------------------------------------- #
def render(evento, palette, fmt_name, index=0):
    fmt = FORMATS[fmt_name]
    W, H = fmt["size"]
    margin = fmt["margin"]
    content_left = margin
    content_width = W - 2 * margin

    categoria = evento["categoria"]
    if categoria not in palette:
        raise ValueError(
            f"Categoria '{categoria}' non presente in palette.json "
            f"(disponibili: {', '.join(palette)})"
        )
    colors = palette[categoria]
    if ALTERNATE_INVERT and index % 2 == 1:
        colors = dict(colors)
        colors["accent1"], colors["accent2"] = \
            colors["accent2"], colors["accent1"]

    # sfondo: colore pieno + logo filigrana centrale + decorazione geometrica
    base = Image.new("RGBA", (W, H), colors["bg"])
    if WATERMARK:
        base = draw_watermark(base, colors)
    if GEOMETRIC_DECOR:
        base = draw_decor(base, categoria, colors)
    draw = ImageDraw.Draw(base)

    # logo in basso a destra, spostato di 1/10 della larghezza verso sinistra
    logo = load_logo(fmt["logo_px"])
    logo_x = W - fmt["logo_pad"] - logo.width - int(W * WATERMARK_SHIFT)
    logo_y = H - fmt["bottom_safe"] - logo.height
    base.paste(logo, (logo_x, logo_y), logo)     # alpha = trasparenza

    # footer in basso a sinistra
    footer_top = draw_footer(draw, evento, fmt, colors, content_left)

    # blocco contenuti centrato tra il margine alto e footer/logo
    elements = build_elements(evento, colors, fmt, content_width)
    stack_h = sum(e["height"] for e in elements) + fmt["gap"] * (len(elements) - 1)

    region_top = margin + fmt["gap"]
    region_bottom = min(footer_top, logo_y) - fmt["gap"]
    start_y = region_top + max(0, (region_bottom - region_top - stack_h) // 2)

    draw_elements(draw, elements, start_y, fmt, colors,
                  content_left, content_width)

    return base.convert("RGB")


# --------------------------------------------------------------------------- #
# Caption
# --------------------------------------------------------------------------- #
def build_hashtags(evento):
    cat_tag = {
        "live_music": "#livemusic", "dj_set_serata": "#djset",
        "aperitivo": "#aperitivo", "festa_special": "#festa",
    }
    tags = ["#isoladelba", "#eventielba", "#elba"]
    if evento["categoria"] in cat_tag:
        tags.append(cat_tag[evento["categoria"]])
    tags.append("#" + slugify(evento["luogo"]))
    tags.append("#" + slugify(evento["nome"]))

    filler = ["#estateallelba", "#musica", "#nightlife", "#weekend"]
    seen, result = set(), []
    for t in tags + filler:
        if t not in seen and len(t) > 1:
            seen.add(t)
            result.append(t)
        if len(result) == 8:
            break
    return result[:8] if len(result) >= 5 else result


def build_caption(evento):
    meta = CATEGORY_META.get(evento["categoria"], CATEGORY_META["_default"])
    nome = evento["nome"]
    sotto = (evento.get("sottotitolo") or "").strip()
    luogo = evento["luogo"]
    locale = (evento.get("locale") or "").strip()
    data = evento["data"]
    ora = evento["ora"]
    contesto = (evento.get("contesto") or "").strip()

    testa = f"{meta['emoji']}{meta['emoji2']} {nome}"
    if sotto:
        testa += f" | {sotto}"
    testa += f" arriva a {luogo}!"

    corpo = (f"Ti aspettiamo {data} {ora} per vivere insieme "
             f"{meta['vibe']}.")
    if locale:
        corpo += f" L'appuntamento è presso {locale}."
    if contesto:
        corpo += f" Un appuntamento speciale di {contesto} da non perdere."

    chiusura = (f"Segna la data e porta con te chi vuoi, sarà una serata "
                f"da ricordare {meta['emoji2']}")

    sede = f"{locale}, {luogo}" if locale else luogo
    hashtags = " ".join(build_hashtags(evento))

    caption = (
        f"{testa}\n"
        f"{corpo}\n"
        f"{chiusura}\n\n"
        f"📍 {sede}\n"
        f"🕒 {ora}\n\n"
        f"{OFFICIAL_HANDLE}\n\n"
        f"{hashtags}\n"
    )
    return caption


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) != 2:
        print("Uso: python3 templates/genera_grafiche.py eventi.json")
        sys.exit(1)

    eventi_path = sys.argv[1]
    if not os.path.isfile(eventi_path):
        print(f"File non trovato: {eventi_path}")
        sys.exit(1)

    with open(eventi_path, "r", encoding="utf-8") as fh:
        eventi = json.load(fh)
    if isinstance(eventi, dict):
        eventi = [eventi]

    palette = load_palette()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for index, evento in enumerate(eventi):
        slug = slugify(evento["nome"])
        for fmt_name in ("post", "story"):
            img = render(evento, palette, fmt_name, index)
            out = os.path.join(OUTPUT_DIR, f"{slug}_{fmt_name}.png")
            img.save(out, "PNG")
            print(f"OK  {out}")

        cap_path = os.path.join(OUTPUT_DIR, f"{slug}_caption.txt")
        with open(cap_path, "w", encoding="utf-8") as fh:
            fh.write(build_caption(evento))
        print(f"OK  {cap_path}")


if __name__ == "__main__":
    main()
