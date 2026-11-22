from __future__ import annotations
import argparse, json, math, os, random, re, time
from datetime import datetime
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
HUD_DIR = Path(__file__).resolve().parent / 'hud'

def default_locale():
    return {}

def locale_logo(loc=None):
    return (loc or {}).get('logo', '')

def locale_fallback_phrase(loc=None):
    return ''

def stage_key(stage):
    return str(stage).strip().lower()
LOGO_TEXT = None
WARM_SHADOW = (110, 62, 32)
HUD_TEXT_STYLE = {'font': '/usr/share/fonts/truetype/sand-box/google/Comfortaa/Comfortaa-VariableFont_wght.ttf', 'weight': 700, 'fill': (255, 244, 226, 255), 'phrase_stroke': 0.8, 'shadows': ((WARM_SHADOW + (40,), 8, 0.4), (WARM_SHADOW + (150,), 1.6, 1.2))}
PAW_TILT = -18
SS = 4
COLORS = {'food': (255, 152, 58), 'cleanliness': (48, 196, 168), 'mood': (255, 196, 64)}
MOOD_ICON = {'sad': 'mood-sad-tears.png', 'ok': 'mood-ok-watercolor.png', 'content': 'mood-content-watercolor.png', 'happy': 'mood-happy-watercolor.png'}
(SOFT_BLUR, SOFT_A) = (18, 58)
(TIGHT_BLUR, TIGHT_DY, TIGHT_A) = (3, 2, 130)

def font(path, size, weight=700):
    font_path = Path(path)
    if not font_path.is_file():
        bundled = HUD_DIR / font_path.name
        if bundled.is_file():
            font_path = bundled
        elif os.name == 'nt':
            windows_fonts = Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'Fonts'
            segoe = windows_fonts / ('segoeuib.ttf' if weight >= 700 else 'segoeui.ttf')
            if segoe.is_file():
                font_path = segoe
        if not font_path.is_file():
            cands = [Path('/usr/share/fonts/truetype/sand-box/google/Comfortaa/Comfortaa-VariableFont_wght.ttf'), Path('/usr/share/fonts/truetype/sand-box/google/Nunito/Nunito-VariableFont_wght.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
            font_path = next((c for c in cands if c.is_file()), None)
            if font_path is None:
                try:
                    return ImageFont.load_default(size=max(1, int(size)))
                except TypeError:
                    return ImageFont.load_default()
    f = ImageFont.truetype(str(font_path), max(1, int(size)))
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f

def clamp(v):
    return max(0, min(100, int(round(float(v)))))

def mood_kind(v):
    if v < 25:
        return 'sad'
    if v < 50:
        return 'ok'
    if v < 75:
        return 'content'
    return 'happy'
LOW_RED = (255, 68, 46)

def low_meter_color(value, base):
    v = float(value)
    b = tuple(base[:3])
    if v >= 35:
        return b
    if v <= 15:
        return LOW_RED
    t = (35.0 - v) / 20.0
    t = t * t * (3.0 - 2.0 * t)
    return tuple((int(round(c + (r - c) * t)) for (c, r) in zip(b, LOW_RED)))

def status_phrase(stats, loc=None):
    return ''

def icon(name, size):
    im = Image.open(HUD_DIR / name).convert('RGBA')
    side = max(1, int(round(size)))
    return im.resize((side, side), Image.Resampling.LANCZOS)

def _blur(im, radius):
    radius = max(1.0, float(radius))
    if radius <= 6:
        return im.filter(ImageFilter.GaussianBlur(radius))
    factor = min(8, max(2, int(radius // 6)))
    (sw, sh) = (max(1, im.size[0] // factor), max(1, im.size[1] // factor))
    small = im.resize((sw, sh), Image.Resampling.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(max(1.0, radius / factor)))
    return small.resize(im.size, Image.Resampling.BILINEAR)

def safe_composite(dst, src, xy):
    (x, y) = (int(round(xy[0])), int(round(xy[1])))
    if x >= 0 and y >= 0:
        dst.alpha_composite(src, (x, y))
        return
    sx = 0 if x >= 0 else -x
    sy = 0 if y >= 0 else -y
    if sx >= src.size[0] or sy >= src.size[1]:
        return
    cropped = src.crop((sx, sy, src.size[0], src.size[1]))
    dst.alpha_composite(cropped, (max(0, x), max(0, y)))

def paste_shadow(layer, alpha_src, color, blur, dx, dy):
    a = alpha_src.split()[-1]
    col = Image.new('RGBA', alpha_src.size, color)
    col.putalpha(a)
    blur = max(1, int(round(blur)))
    pad = blur * 2
    wrapped = Image.new('RGBA', (col.size[0] + 2 * pad, col.size[1] + 2 * pad), (0, 0, 0, 0))
    wrapped.alpha_composite(col, (pad, pad))
    wrapped = _blur(wrapped, blur)
    safe_composite(layer, wrapped, (int(dx) - pad, int(dy) - pad))

def double_shadow(layer, src, x, y, s, soft_a=SOFT_A, tight_a=TIGHT_A):
    paste_shadow(layer, src, (0, 0, 0, soft_a), blur=SOFT_BLUR * s, dx=x, dy=y)
    paste_shadow(layer, src, (0, 0, 0, tight_a), blur=TIGHT_BLUR * s, dx=x, dy=y + TIGHT_DY * s)

def raster_text(text, font_, fill, stroke=0):
    dummy = ImageDraw.Draw(Image.new('RGBA', (1, 1), (0, 0, 0, 0)))
    (x0, y0, x1, y1) = dummy.textbbox((0, 0), text, font=font_, stroke_width=stroke)
    pad = 4
    im = Image.new('RGBA', (int(x1 - x0 + 2 * pad), int(y1 - y0 + 2 * pad)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - x0, pad - y0), text, font=font_, fill=fill, stroke_width=stroke, stroke_fill=fill)
    return (im, (x0 - pad, y0 - pad))

def paste_warm_shadow(layer, src, x, y, s, soft_a=34, tight_a=88):
    paste_shadow(layer, src, WARM_SHADOW + (soft_a,), blur=14 * s, dx=x, dy=y + 0.4 * s)
    paste_shadow(layer, src, WARM_SHADOW + (tight_a,), blur=3.4 * s, dx=x, dy=y + 1.8 * s)

def hud_font(size):
    return font(HUD_TEXT_STYLE['font'], size, HUD_TEXT_STYLE['weight'])

def paste_hud_text(layer, xy, text, font_, s, stroke=0):
    (im, (ox, oy)) = raster_text(text, font_, HUD_TEXT_STYLE['fill'], stroke)
    (x, y) = (int(xy[0] + ox), int(xy[1] + oy))
    for (color, blur, offset_y) in HUD_TEXT_STYLE['shadows']:
        paste_shadow(layer, im, color, blur=blur * s, dx=x, dy=y + offset_y * s)
    layer.alpha_composite(im, (x, y))
TUBE_START = 135.0
TUBE_SPAN = 270.0

def _tube_field(h, w, cx, cy, R, half_w, start, span):
    (ys, xs) = np.ogrid[0:h, 0:w]
    xs = xs.astype(np.float32)
    ys = ys.astype(np.float32)
    dx = xs - np.float32(cx)
    dy = ys - np.float32(cy)
    dist = np.sqrt(dx * dx + dy * dy)
    ang = np.degrees(np.arctan2(dy, dx))
    u = (dist - R) / max(half_w, 1e-06)
    in_span = (ang - start) % 360.0 <= span
    body = in_span & (np.abs(u) <= 1.0)
    cap_d = np.full((h, w), np.inf, dtype=np.float32)
    cap_dy = np.zeros_like(cap_d)
    for t in (start, start + span):
        a = math.radians(t)
        px = cx + R * math.cos(a)
        py = cy + R * math.sin(a)
        dcap = np.sqrt((xs - px) ** 2 + (ys - py) ** 2)
        cap_dy = np.where(dcap < cap_d, py - ys, cap_dy)
        cap_d = np.minimum(cap_d, dcap)
        body = body | (dcap <= half_w)
    end_caps = (cap_d <= half_w) & ~in_span
    edge = half_w * (1.0 - np.abs(np.clip(u, -1.0, 1.0)))
    edge = np.where(end_caps, half_w - cap_d, edge)
    medial_y = cy + R * np.sin(np.radians(ang))
    height_above_center = np.where(end_caps, cap_dy, medial_y - ys)
    upness = np.clip(height_above_center / half_w, -1.0, 1.0)
    return (body, u, edge, dist, ang, upness, xs, ys)

def juicy_rgb(rgb):
    (r, g, b) = (c / 255.0 for c in rgb[:3])
    avg = (r + g + b) / 3.0
    (r, g, b) = (avg + (c - avg) * 1.38 for c in (r, g, b))
    (r, g, b) = (min(1.0, max(0.0, c * 1.08)) for c in (r, g, b))
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))

def _liquid_layer(h, w, cx, cy, R, half_w, start, span, value, color, s):
    v = max(0.0, min(100.0, float(value)))
    if v <= 0.05:
        return (Image.new('RGBA', (w, h), (0, 0, 0, 0)), None)
    liq_span = TUBE_SPAN * v / 100.0
    (body, u, edge, dist, ang, upness, xs, ys) = _tube_field(h, w, cx, cy, R, half_w, start, liq_span)
    t = np.clip(1.0 - edge / half_w, 0.0, 1.0)
    mid = np.array(juicy_rgb(color[:3]), dtype=np.float32)
    shadow_color = mid * np.array((0.69, 0.31, 0.44), dtype=np.float32)
    underside = np.clip((0.16 - upness) / 1.16, 0, 1)
    shade = underside ** 0.78
    col = mid + (shadow_color - mid) * shade[..., None]
    col *= (1.0 - 0.14 * t ** 2)[..., None]
    shoulder = 0.32 * np.exp(-((upness - 0.43) / 0.37) ** 2)
    warm_light = np.array((255, 247, 225), dtype=np.float32)
    col += (warm_light - col) * shoulder[..., None]
    col = np.clip(col, 0, 255)
    alpha = body.astype(np.float32) * 255.0
    alpha = alpha * np.clip(edge / max(0.55 * s, 0.8), 0, 1)
    im = np.zeros((h, w, 4), dtype=np.uint8)
    im[..., :3] = col.astype(np.uint8)
    im[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    return (Image.fromarray(im, 'RGBA'), body)

def _tube_highlights(h, w, body, empty, edge, upness, xs, ys, cx, cy, R, half_w, s, night=False):
    bm = body.astype(np.float32)
    out = np.zeros((h, w, 4), dtype=np.float32)

    def add(rgb, a):
        a = np.clip(a, 0, 1)
        src_a = a[..., None]
        src_c = np.array(rgb, dtype=np.float32)[None, None, :]
        dst_a = out[..., 3:4] / 255.0
        out_a = src_a + dst_a * (1.0 - src_a)
        with np.errstate(invalid='ignore'):
            col = (src_c * src_a + out[..., :3] * dst_a * (1.0 - src_a)) / np.maximum(out_a, 1e-06)
        out[..., :3] = np.where(out_a > 0, col, out[..., :3])
        out[..., 3] = (out_a * 255.0)[..., 0]
    inside = empty * np.clip(edge / max(0.6 * s, 1), 0, 1)
    lower_wall = np.clip(-upness, 0, 1) ** 0.75
    add((36, 51, 72), inside * lower_wall * (0.36 if night else 0.6))
    upper_wall = np.exp(-((upness - 0.36) / 0.38) ** 2)
    add((243, 250, 255), inside * upper_wall * 0.42)
    rim_w = max(1.15, (0.95 if night else 0.65) * s)
    rim = np.clip(1.0 - edge / rim_w, 0, 1) ** 1.05
    add((255, 250, 240) if night else (255, 255, 255), rim * bm * (0.78 if night else 0.63))
    streak = np.exp(-((upness - 0.52) / 0.14) ** 2) * bm
    streak = streak * np.clip((edge - 0.45 * s) / max(half_w * 0.3, 1), 0, 1)
    add((255, 255, 255), streak * (0.76 if night else 0.68))
    secondary = np.exp(-((upness + 0.69) / 0.16) ** 2) * bm
    secondary *= np.clip(edge / max(half_w * 0.26, 1), 0, 1)
    add((224, 246, 255), secondary * 0.25)
    a = math.radians(248)
    px = cx + R * math.cos(a)
    py = cy + R * math.sin(a) - 0.38 * half_w
    d = np.sqrt((xs - px) ** 2 + (ys - py) ** 2)
    dot = np.exp(-(d / (half_w * 0.32)) ** 2) * bm
    add((255, 255, 255), dot * 0.58)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')

def _tube_backdrop(photo, x0, y0, w, h, ss, empty, s, night=False):
    (w1, h1) = (max(1, int(round(w / ss))), max(1, int(round(h / ss))))
    (W, H) = photo.size
    (sx0, sy0) = (x0 / ss, y0 / ss)
    (ix0, iy0) = (int(math.floor(sx0)), int(math.floor(sy0)))
    (ix1, iy1) = (ix0 + w1, iy0 + h1)
    canvas = Image.new('RGB', (w1, h1), (80, 70, 80))
    src = photo.crop((max(0, ix0), max(0, iy0), min(W, ix1), min(H, iy1)))
    canvas.paste(src, (max(0, -ix0) if ix0 < 0 else 0, max(0, -iy0) if iy0 < 0 else 0))
    blur1 = max(2, int(round(5 * (s / ss))))
    frosted = canvas.filter(ImageFilter.GaussianBlur(blur1))
    frosted = ImageEnhance.Brightness(frosted).enhance(1.16 if night else 1.02)
    frost_a = frosted.convert('RGBA')
    milk = Image.new('RGBA', frost_a.size, (236, 244, 255, 70 if night else 12))
    frost_a = Image.alpha_composite(frost_a, milk)
    mask1 = Image.fromarray(empty.astype(np.uint8) * 255, 'L').resize((w1, h1), Image.Resampling.BILINEAR)
    mask1 = mask1.filter(ImageFilter.GaussianBlur(0.6))
    frost_a.putalpha(mask1)
    return frost_a.resize((w, h), Image.Resampling.LANCZOS)

def _tube_contact_shadow(w, h, body, s):
    tube_rgba = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    tube_rgba.putalpha(Image.fromarray(body.astype(np.uint8) * 255, 'L'))
    patch = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    paste_shadow(patch, tube_rgba, (111, 91, 76, 32), blur=10 * s, dx=0, dy=int(1.0 * s))
    paste_shadow(patch, tube_rgba, (111, 91, 76, 35), blur=3.8 * s, dx=0, dy=int(1.5 * s))
    pa = np.array(patch)
    pa[..., 3] = (pa[..., 3].astype(np.float32) * (1.0 - body.astype(np.float32) * 0.97)).astype(np.uint8)
    return Image.fromarray(pa, 'RGBA')

def _matte_band(body, edge, upness, color, opacity, s):
    light = np.clip(0.5 + 0.5 * upness, 0, 1)
    rgb = np.asarray(color, dtype=np.float32)
    shade = rgb * 0.82
    tint = rgb + (np.array((255, 242, 218)) - rgb) * 0.18
    pixels = np.empty((*body.shape, 4), dtype=np.uint8)
    pixels[..., :3] = shade + (tint - shade) * light[..., None]
    coverage = np.clip(edge / max(0.8 * s, 1), 0, 1)
    pixels[..., 3] = body * coverage * opacity
    return Image.fromarray(pixels, 'RGBA')

def draw_gauge_tube(photo, layer, cx, cy, r, value, color, icon_name, s, ss, night=False, style='glass'):
    ring_w = max(ss, int(round((0.18 if style == 'matte' else 0.24) * r)))
    half_w = ring_w / 2.0
    R = r
    (start, span) = (TUBE_START, TUBE_SPAN)
    col = low_meter_color(value, color)
    pad = int(22 * s + ring_w)
    x0 = int(cx - r - pad)
    y0 = int(cy - r - pad)
    side = int(2 * r + 2 * pad)
    h = w = side
    (lcx, lcy) = (cx - x0, cy - y0)
    (body, u, edge, dist, ang, upness, xs, ys) = _tube_field(h, w, lcx, lcy, R, half_w, start, span)
    patch = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    if style == 'matte':
        track = (233, 222, 195) if night else (111, 91, 76)
        patch.alpha_composite(_matte_band(body, edge, upness, track, 125, s))
        if value > 0:
            (fill, _, fill_edge, _, _, fill_light, _, _) = _tube_field(h, w, lcx, lcy, R, half_w, start, span * value / 100)
            pigment = tuple((0.82 * channel + 0.18 * neutral for (channel, neutral) in zip(col, (225, 199, 166))))
            patch.alpha_composite(_matte_band(fill, fill_edge, fill_light, pigment, 247, s))
    else:
        _draw_glass_band(photo, patch, x0, y0, w, h, ss, body, edge, upness, xs, ys, lcx, lcy, R, half_w, start, span, value, col, s, night)
    inner = (r - max(ss, round(0.24 * r))) * 2 * 0.7
    ic_im = icon(icon_name, inner)
    ix = int(lcx - ic_im.size[0] / 2)
    iy = int(lcy - ic_im.size[1] / 2)
    if night:
        paste_shadow(patch, ic_im, (255, 246, 230, 80), blur=6 * s, dx=ix, dy=iy)
    if style == 'matte':
        paste_shadow(patch, ic_im, (63, 42, 29, 70), blur=4 * s, dx=ix, dy=iy + s)
    else:
        paste_shadow(patch, ic_im, (111, 91, 76, 35), blur=10 * s, dx=ix, dy=iy)
        paste_shadow(patch, ic_im, (111, 91, 76, 80), blur=4 * s, dx=ix, dy=iy + 1.5 * s)
    patch.alpha_composite(ic_im, (ix, iy))
    safe_composite(layer, patch, (x0, y0))

def _draw_glass_band(photo, patch, x0, y0, w, h, ss, body, edge, upness, xs, ys, lcx, lcy, R, half_w, start, span, value, col, s, night):
    if night:
        glo = _blur(Image.fromarray(body.astype(np.uint8) * 255, 'L'), 5.0 * s)
        ga = np.clip(np.array(glo, dtype=np.float32) * 0.55, 0, 150)
        ga = ga * (1.0 - body.astype(np.float32) * 0.96)
        halo = np.zeros((h, w, 4), dtype=np.uint8)
        (halo[..., 0], halo[..., 1], halo[..., 2]) = (255, 246, 230)
        halo[..., 3] = ga.astype(np.uint8)
        patch.alpha_composite(Image.fromarray(halo, 'RGBA'))
    patch.alpha_composite(_tube_contact_shadow(w, h, body, s))
    (liq, liq_body) = _liquid_layer(h, w, lcx, lcy, R, half_w, start, span, value, col, s)
    empty = body.copy()
    if liq_body is not None:
        empty = body & ~liq_body
    if np.any(empty):
        patch.alpha_composite(_tube_backdrop(photo, x0, y0, w, h, ss, empty, s, night=night))
    if liq is not None:
        patch.alpha_composite(liq)
    patch.alpha_composite(_tube_highlights(h, w, body, empty, edge, upness, xs, ys, lcx, lcy, R, half_w, s, night=night))

def draw_logo(layer, s, margin, text=None):
    logo = text if text is not None else LOGO_TEXT
    paw = icon('paw-watercolor.png', 46 * s)
    paw = paw.rotate(PAW_TILT, resample=Image.Resampling.BICUBIC, expand=True)
    bbox = paw.split()[-1].getbbox()
    if bbox:
        paw = paw.crop(bbox)
    fnt = hud_font(30 * s)
    dummy = ImageDraw.Draw(layer)
    tb = dummy.textbbox((0, 0), logo, font=fnt)
    (tw, th) = (tb[2] - tb[0], tb[3] - tb[1])
    gap = int(16 * s)
    x = int(margin)
    y = int(margin)
    paw_y = y + max(0, (th - paw.size[1]) // 2)
    text_y = y + max(0, (paw.size[1] - th) // 2) - int(2 * s)
    text_x = x + paw.size[0] + gap
    paste_warm_shadow(layer, paw, x, paw_y, s, soft_a=36, tight_a=90)
    layer.alpha_composite(paw, (x, paw_y))
    paste_hud_text(layer, (text_x, text_y), logo, fnt, s)
    bottom = max(paw_y + paw.size[1], text_y + tb[3])
    return (x, bottom)

def _fit_line(text, size, max_w, min_size):
    dummy = ImageDraw.Draw(Image.new('RGBA', (1, 1), (0, 0, 0, 0)))
    (size, min_size) = (int(round(size)), int(round(min_size)))
    for sz in range(max(size, min_size), min_size - 1, -1):
        fnt = hud_font(sz)
        tb = dummy.textbbox((0, 0), text, font=fnt)
        if tb[2] - tb[0] <= max_w:
            return (fnt, text, tb)
    fnt = hud_font(min_size)
    t = text
    while t and dummy.textbbox((0, 0), t + '…', font=fnt)[2] > max_w:
        t = t[:-1]
    t = t + '…' if t != text else t
    if not t:
        t = '…'
    return (fnt, t, dummy.textbbox((0, 0), t, font=fnt))

def draw_name_age(layer, s, x, y, W, margin, name, stage, age):
    if stage and age:
        meta = f'{stage} · {age}'
    else:
        meta = stage or age or ''
    if not name and (not meta):
        return
    max_w = max(1, int(W - margin - x))
    y = int(y + 10 * s)
    if name:
        (fnt, text, tb) = _fit_line(name, 26 * s, max_w, 18 * s)
        paste_hud_text(layer, (x, y - tb[1]), text, fnt, s)
        y = y + (tb[3] - tb[1]) + int(7 * s)
    if meta:
        (fnt, text, tb) = _fit_line(meta, 18 * s, max_w, 13 * s)
        paste_hud_text(layer, (x, y - tb[1]), text, fnt, s)

def _gauges_right(s, margin):
    radius = 43 * s
    gap = 0.3 * (2 * radius)
    x0 = margin + radius
    last_cx = x0 + 2 * (2 * radius + gap)
    return last_cx + radius

def _wrap_phrase(text, fnt, max_w):
    dummy = ImageDraw.Draw(Image.new('RGBA', (8, 8)))
    words = text.split()
    if len(words) < 2:
        return None
    best = None
    for i in range(1, len(words)):
        (a, b) = (' '.join(words[:i]), ' '.join(words[i:]))
        ta = dummy.textbbox((0, 0), a, font=fnt)
        tb = dummy.textbbox((0, 0), b, font=fnt)
        (wa, wb) = (ta[2] - ta[0], tb[2] - tb[0])
        (ha, hb) = (ta[3] - ta[1], tb[3] - tb[1])
        if wa <= max_w and wb <= max_w:
            width = max(wa, wb)
            score = width + abs(wa - wb) * 0.25
            if best is None or score < best[0]:
                best = (score, [a, b], width, ha, hb)
    if best is None:
        return None
    return (best[1], best[2], best[3], best[4])

def fit_status_phrase(phrase, s, max_w, fallback=None):
    dummy = ImageDraw.Draw(Image.new('RGBA', (8, 8)))
    phrase = (phrase or '').strip() or (fallback if fallback is not None else locale_fallback_phrase())
    (size0, min_size) = (round(23.4 * s), round(14.4 * s))
    for sz in range(max(size0, min_size), min_size - 1, -1):
        fnt = hud_font(sz)
        tb = dummy.textbbox((0, 0), phrase, font=fnt)
        if tb[2] - tb[0] <= max_w:
            return (fnt, [phrase], tb[2] - tb[0], tb[3] - tb[1], 0)
    for sz in range(max(size0, min_size), min_size - 1, -1):
        fnt = hud_font(sz)
        wrapped = _wrap_phrase(phrase, fnt, max_w)
        if not wrapped:
            continue
        (lines, width, h1, h2) = wrapped
        gap = int(4 * s)
        return (fnt, lines, width, h1 + gap + h2, gap)
    fnt = hud_font(min_size)
    t = phrase
    while t and dummy.textbbox((0, 0), t + '…', font=fnt)[2] - dummy.textbbox((0, 0), '', font=fnt)[0] > max_w:
        t = t[:-1]
    t = t + '…' if t != phrase else t
    if not t:
        t = '…'
    tb = dummy.textbbox((0, 0), t, font=fnt)
    return (fnt, [t], tb[2] - tb[0], tb[3] - tb[1], 0)

def draw_status(layer, s, margin, W, H, phrase, egg=False, fallback=None):
    heart = icon('heart-watercolor.png', 46 * s)
    gap = int(8 * s)
    if egg:
        left_limit = int(margin)
    else:
        left_limit = int(_gauges_right(s, margin) + 16 * s)
    max_w = max(1, int(W - margin - left_limit - heart.size[0] - gap))
    (fnt, lines, tw, th, line_gap) = fit_status_phrase(phrase, s, max_w, fallback=fallback)
    total_w = heart.size[0] + gap + tw
    x = int(W - margin - total_w)
    y = int(H - margin - max(heart.size[1], th))
    text_x = x + heart.size[0] + gap
    text_y = y + max(0, (heart.size[1] - th) // 2) - int(2 * s)
    dummy = ImageDraw.Draw(Image.new('RGBA', (8, 8)))
    text_mid = text_y + dummy.textbbox((0, 0), lines[0], font=fnt)[1] + th / 2
    hb = heart.getchannel('A').getbbox() or (0, 0, heart.size[0], heart.size[1])
    heart_y = round(text_mid - (hb[1] + hb[3]) / 2 - 4 * s)
    double_shadow(layer, heart, x, heart_y, s, soft_a=55, tight_a=135)
    layer.alpha_composite(heart, (x, heart_y))
    y_line = text_y
    dummy = ImageDraw.Draw(Image.new('RGBA', (8, 8)))
    for (i, line) in enumerate(lines):
        tb = dummy.textbbox((0, 0), line, font=fnt)
        (lw, lh) = (tb[2] - tb[0], tb[3] - tb[1])
        paste_hud_text(layer, (text_x + (tw - lw), y_line), line, fnt, s, stroke=max(1, round(HUD_TEXT_STYLE['phrase_stroke'] * s)))
        y_line += lh + (line_gap if i == 0 else 0)

def _region_luma(photo, box):
    (x0, y0, x1, y1) = (int(math.floor(box[0])), int(math.floor(box[1])), int(math.ceil(box[2])), int(math.ceil(box[3])))
    (W, H) = photo.size
    crop = photo.crop((max(0, x0), max(0, y0), min(W, max(x0 + 1, x1)), min(H, max(y0 + 1, y1))))
    if crop.size[0] < 1 or crop.size[1] < 1:
        return 128.0
    small = crop.resize((32, 16), Image.Resampling.BILINEAR)
    a = np.asarray(small, dtype=np.float32)
    return float((0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]).mean())

def _save(im, out):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(out).suffix.lower()
    rgb = im.convert('RGB')
    if ext == '.png':
        rgb.save(out, 'PNG', optimize=False, compress_level=3)
    else:
        rgb.save(out, quality=92, subsampling=0)

def render(inp, out, stats, name='', clean_icon=None, stage='', age='', phrase=None, gauge_style='glass', locale=None):
    loc = locale or default_locale()
    egg = stage_key(stage) == 'egg'
    photo = Image.open(inp).convert('RGB')
    (W, H) = photo.size
    s = W / 1152
    ss = SS
    s_hi = s * ss
    (W_hi, H_hi) = (W * ss, H * ss)
    layer_hi = Image.new('RGBA', (W_hi, H_hi), (0, 0, 0, 0))
    margin = 28 * s_hi
    (logo_x, logo_bottom) = draw_logo(layer_hi, s_hi, margin, text=locale_logo(loc))
    if not egg:
        draw_name_age(layer_hi, s_hi, logo_x, logo_bottom, W_hi, margin, name, stage, age)
        radius = 43 * s_hi
        gap = 0.3 * (2 * radius)
        cy = H_hi - margin - radius
        x0 = margin + radius
        food = float((stats or {}).get('food', 0))
        clean = float((stats or {}).get('cleanliness', (stats or {}).get('clean', 0)))
        mood = float((stats or {}).get('mood', 0))
        gauges = [(food, COLORS['food'], 'bowl-watercolor.png'), (clean, COLORS['cleanliness'], clean_icon or os.environ.get('HUD_CLEAN_ICON') or 'clean-paw.png'), (mood, COLORS['mood'], MOOD_ICON[mood_kind(clamp(mood))])]
        last_cx = x0 + (len(gauges) - 1) * (2 * radius + gap)
        luma_box = ((x0 - radius) / ss, (cy - radius) / ss, (last_cx + radius) / ss, (cy + radius) / ss)
        night = _region_luma(photo, luma_box) < 110
        for (i, (value, color, ic_name)) in enumerate(gauges):
            cx = x0 + i * (2 * radius + gap)
            draw_gauge_tube(photo, layer_hi, cx, cy, radius, value, color, ic_name, s_hi, ss, night=night, style=gauge_style)
    line = phrase or status_phrase(stats, loc=loc)
    draw_status(layer_hi, s_hi, margin, W_hi, H_hi, line, egg=egg, fallback=locale_fallback_phrase(loc))
    layer = layer_hi.resize((W, H), Image.Resampling.LANCZOS)
    result = Image.alpha_composite(photo.convert('RGBA'), layer)
    _save(result, out)
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument('inp')
    p.add_argument('out')
    p.add_argument('--logo', required=True)
    p.add_argument('--phrase', required=True)
    p.add_argument('--stats', default='{}')
    p.add_argument('--name', default='')
    p.add_argument('--stage', default='')
    p.add_argument('--age', default='')
    p.add_argument('--egg', action='store_true')
    p.add_argument('--clean-icon')
    p.add_argument('--gauge-style', choices=('glass', 'matte'), default='glass')
    a = p.parse_args()
    render(a.inp, a.out, json.loads(a.stats), a.name, clean_icon=a.clean_icon, stage='egg' if a.egg else a.stage, age=a.age, phrase=a.phrase, gauge_style=a.gauge_style, locale={'logo': a.logo})
if __name__ == '__main__':
    main()
