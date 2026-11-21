#!/usr/bin/env python3
"""The Passport Page of a Country That Isn't There.

Draws an invented passport spread for the fictional Republic of Kaveria
entirely in pure-stdlib Python (no network, no third-party packages) and
writes it to /output/entry.png (1024x1024, well under 1 MiB).

The country is invented but internally consistent: capital Drenovar,
citizen Elena Marovic, passport issued 12 JUN 2023 in Drenovar, expiring
12 JUN 2033. Every stamp is dated after the issue date and tells one
plausible travel history through the three neighbouring countries shown
on the little map on the data page: Velmara (Sep 2023), Ostrovia
(Jan 2024), Tarnovia (May-Jun 2024). The telling paperwork detail is a
red condition stamp (employment prohibited, tourist stay 90 days) plus a
consular fee stamp for 40 KAV.
"""

import base64
import json
import math
import os
import struct
import zlib

W, H = 1024, 1024


# ---------------------------------------------------------------- canvas
class Canvas:
    """Simple RGB canvas with a per-pixel alpha channel."""

    def __init__(self, w, h, color=None):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)
        self.alpha = bytearray(w * h)
        if color is not None:
            self.fill_rect(0, 0, w, h, color)

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i:i + 3] = bytes(c)
            self.alpha[y * self.w + x] = 255

    def set_blend(self, x, y, c, a):
        """Blend colour c over the pixel with strength a (0..255)."""
        if 0 <= x < self.w and 0 <= y < self.h and a > 0:
            i = (y * self.w + x) * 3
            if a >= 255:
                self.buf[i:i + 3] = bytes(c)
            else:
                for k in range(3):
                    self.buf[i + k] = (c[k] * a + self.buf[i + k] * (255 - a)) // 255
            self.alpha[y * self.w + x] = 255

    def _hspan(self, x0, x1, y, c, a=255):
        if y < 0 or y >= self.h:
            return
        x0 = max(0, x0)
        x1 = min(self.w - 1, x1)
        if x1 < x0:
            return
        n = x1 - x0 + 1
        i = (y * self.w + x0) * 3
        if a >= 255:
            self.buf[i:i + 3 * n] = bytes(c) * n
            self.alpha[y * self.w + x0:y * self.w + x1 + 1] = bytes([255]) * n
        else:
            for x in range(x0, x1 + 1):
                self.set_blend(x, y, c, a)

    def fill_rect(self, x0, y0, x1, y1, c, a=255):
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w - 1, x1)
        y1 = min(self.h - 1, y1)
        for y in range(y0, y1 + 1):
            self._hspan(x0, x1, y, c, a)

    def rect(self, x0, y0, x1, y1, c, wd=1):
        for t in range(wd):
            self._hspan(x0, x1, y0 + t, c)
            self._hspan(x0, x1, y1 - t, c)
            for y in range(y0, y1 + 1):
                self.set(x0 + t, y, c)
                self.set(x1 - t, y, c)

    def circle(self, cx, cy, r, c, a=255):
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            self._hspan(cx - dx, cx + dx, cy + dy, c, a)

    def ring(self, cx, cy, r, c, wd=2, a=255):
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            dx2 = int(max(0, (r - wd) * (r - wd) - dy * dy) ** 0.5) if abs(dy) < r - wd else 0
            self._hspan(cx - dx, cx - dx2, cy + dy, c, a)
            self._hspan(cx + dx2, cx + dx, cy + dy, c, a)

    def ellipse(self, cx, cy, rx, ry, c, a=255):
        for dy in range(-ry, ry + 1):
            t = 1.0 - (dy * dy) / float(ry * ry)
            dx = int(rx * (t ** 0.5)) if t > 0 else 0
            self._hspan(cx - dx, cx + dx, cy + dy, c, a)

    def poly(self, pts, c, a=255):
        ys = [p[1] for p in pts]
        y0 = max(0, min(ys))
        y1 = min(self.h - 1, max(ys))
        n = len(pts)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                x0, yy0 = pts[i]
                x1, yy1 = pts[(i + 1) % n]
                if (yy0 <= y < yy1) or (yy1 <= y < yy0):
                    t = (y - yy0) / float(yy1 - yy0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                self._hspan(int(xs[i]), int(xs[i + 1]), y, c, a)

    def line(self, x0, y0, x1, y1, c, wd=1):
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        steps = max(dx, dy, 1)
        for s in range(steps + 1):
            t = s / float(steps)
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            if wd <= 1:
                self.set(x, y, c)
            else:
                self.circle(x, y, wd // 2, c)

    def polyline(self, pts, c, wd=1):
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], c, wd)

    def blit(self, src, x0, y0):
        for y in range(src.h):
            dy = y0 + y
            if dy < 0 or dy >= self.h:
                continue
            for x in range(src.w):
                dx = x0 + x
                if dx < 0 or dx >= self.w:
                    continue
                a = src.alpha[y * src.w + x]
                if a == 255:
                    i = (dy * self.w + dx) * 3
                    j = (y * src.w + x) * 3
                    self.buf[i:i + 3] = src.buf[j:j + 3]
                    self.alpha[dy * self.w + dx] = 255
                elif a:
                    i = (dy * self.w + dx) * 3
                    j = (y * src.w + x) * 3
                    for k in range(3):
                        self.buf[i + k] = (src.buf[j + k] * a + self.buf[i + k] * (255 - a)) // 255
                    self.alpha[dy * self.w + dx] = 255


def rotate(src, angle_deg):
    """Rotate a canvas by angle_deg (nearest neighbour, transparent bg)."""
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    w, h = src.w, src.h
    nw = int(abs(w * cos_a) + abs(h * sin_a)) + 2
    nh = int(abs(w * sin_a) + abs(h * cos_a)) + 2
    out = Canvas(nw, nh)
    cx, cy = w / 2.0, h / 2.0
    ncx, ncy = nw / 2.0, nh / 2.0
    for y in range(nh):
        for x in range(nw):
            dx = x - ncx
            dy = y - ncy
            sx = int(round(cx + dx * cos_a + dy * sin_a))
            sy = int(round(cy - dx * sin_a + dy * cos_a))
            if 0 <= sx < w and 0 <= sy < h:
                a = src.alpha[sy * w + sx]
                if a:
                    i = (sy * w + sx) * 3
                    j = (y * nw + x) * 3
                    out.buf[j:j + 3] = src.buf[i:i + 3]
                    out.alpha[y * nw + x] = a
    return out


# ------------------------------------------------------------------- text
# GLYPH_DATA is defined below (embedded DejaVu-derived 1-bit bitmaps).
_GLYPH_CACHE = {}


def _glyph(spec, ch):
    key = (spec, ch)
    g = _GLYPH_CACHE.get(key)
    if g is None:
        glyphs = GLYPHS[spec]
        rec = glyphs.get(ch) or glyphs.get("?") or glyphs.get(" ")
        w, h, adv, offx, offy, b64 = rec
        g = (w, h, adv, offx, offy, base64.b64decode(b64))
        _GLYPH_CACHE[key] = g
    return g


def text_width(s, spec):
    return sum(_glyph(spec, ch)[2] for ch in s)


def draw_text(cv, s, spec, x, y_base, color, align="left", spacing=0):
    total = sum(_glyph(spec, ch)[2] + spacing for ch in s) - spacing
    if align == "center":
        x -= total // 2
    elif align == "right":
        x -= total
    asc = ASC[spec]
    for ch in s:
        w, h, adv, offx, offy, bits = _glyph(spec, ch)
        gx0 = x + offx
        gy0 = y_base - asc + offy
        for gy in range(h):
            row = gy * w
            for gx in range(w):
                bit = row + gx
                if bits[bit >> 3] >> (7 - (bit & 7)) & 1:
                    cv.set(gx0 + gx, gy0 + gy, color)
        x += adv + spacing


# -------------------------------------------------------------------- png
def png_bytes(cv):
    raw = bytearray()
    for y in range(cv.h):
        raw.append(0)
        raw += cv.buf[y * cv.w * 3:(y + 1) * cv.w * 3]
    comp = zlib.compress(bytes(raw), 6)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


# ------------------------------------------------------------------ stamps
def make_stamp(lines, ink, w, h, double=True):
    """A rectangular ink stamp; lines = [(text, spec, color), ...]."""
    cv = Canvas(w, h)
    cv.rect(2, 2, w - 3, h - 3, ink, wd=3)
    if double:
        cv.rect(8, 8, w - 9, h - 9, ink, wd=1)
    n = len(lines)
    top = 14
    usable = h - 2 * top
    for i, (text, spec, color) in enumerate(lines):
        yb = top + int((i + 0.5) * usable / n) + ASC[spec] // 2
        draw_text(cv, text, spec, w // 2, yb, color, align="center")
    return cv


def mrz_check(s):
    vals = {}
    for i in range(10):
        vals[str(i)] = i
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        vals[ch] = 10 + i
    vals["<"] = 0
    total = 0
    for i, ch in enumerate(s):
        total += vals[ch] * (7, 3, 1)[i % 3]
    return str(total % 10)


def mrz_lines():
    name = "MAROVIC<<ELENA".ljust(39, "<")
    line1 = ("P<KAV" + name)[:44]
    doc = "KV4829173"
    dob = "910314"
    exp = "330612"
    personal = "<" * 14
    core = (doc + mrz_check(doc) + "KAV" + dob + mrz_check(dob) + "F"
            + exp + mrz_check(exp) + personal)
    line2 = core + mrz_check(core[:10] + core[13:19] + core[21:27]) + mrz_check(personal)
    # line2 must be 44 chars: doc(9)+cd+nat(3)+dob(6)+cd+sex(1)+exp(6)+cd
    # + personal(14)+cd+composite(1)
    line2 = (doc + mrz_check(doc) + "KAV" + dob + mrz_check(dob) + "F"
             + exp + mrz_check(exp) + personal + mrz_check(personal)
             + mrz_check(doc + mrz_check(doc) + dob + mrz_check(dob)
                         + exp + mrz_check(exp)))
    return line1, line2


# ------------------------------------------------------- embedded glyphs
_GLYPH_JSON = (
r'''{"asc":{"r10":10,"r12":12,"b14":13,"b16":15,"b30":28,"m15":14},"glyphs":{"r10":{"A":[7,7,7,0,3,"EFCiB8iggA=="],"B":[7,7,7,0,3,"eIkTxEieAA=="],"C":[7,7,7,0,3,"PMECBAwPAA=="],"D":[8,7,8,0,3,"fEZCQkJGfA=="],"E":[6,7,6,0,3,"fQQeQQfA"],"F":[6,7,6,0,3,"eQQeQQQA"],"G":[8,7,8,0,3,"PGJATkJiPA=="],"H":[8,7,8,0,3,"QkJCfkJCQg=="],"I":[3,7,3,0,3,"SSSQ"],"J":[4,9,3,-1,3,"IiIiIsA="],"K":[7,7,7,0,3,"RJHDBQkRAA=="],"L":[6,7,6,0,3,"QQQQQQfA"],"M":[9,7,9,0,3,"YzGRSqWSSQQ="],"N":[7,7,7,0,3,"YsVKlKnRgA=="],"O":[8,7,8,0,3,"PGZCQkJmPA=="],"P":[6,7,6,0,3,"eTTeQQQA"],"Q":[8,8,8,0,3,"PGZCQkJmPAQ="],"R":[7,7,7,0,3,"eJkzxIiRAA=="],"S":[6,7,6,0,3,"eQQOBDeA"],"T":[8,7,6,-1,3,"fggICAgICA=="],"U":[7,7,7,0,3,"RIkSJEiOAA=="],"V":[7,7,7,0,3,"gokSQocEAA=="],"W":[10,7,10,0,3,"jJMkyUITDMMw"],"X":[7,7,7,0,3,"RFDggokRAA=="],"Y":[8,7,6,-1,3,"QiQYGAgICA=="],"Z":[7,7,7,0,3,"fAggggg/AA=="],"a":[6,5,6,0,5,"cCeSeA=="],"b":[6,8,6,0,2,"QQQeTRTe"],"c":[6,5,6,0,5,"OQQQOA=="],"d":[6,8,6,0,2,"AAAeSQSe"],"e":[6,5,6,0,5,"OSfQOA=="],"f":[4,8,4,0,2,"NE5ERA=="],"g":[6,7,6,0,5,"eSQSeCcA"],"h":[6,8,6,0,2,"QQQeSQQQ"],"i":[3,8,3,0,2,"QCSS"],"j":[4,10,3,-1,2,"IAIiIiQ="],"k":[6,8,6,0,2,"QQQSUYUS"],"l":[3,8,3,0,2,"SSSS"],"m":[10,5,10,0,5,"exMkiSJIgA=="],"n":[6,5,6,0,5,"eSQQQA=="],"o":[6,5,6,0,5,"OSRSOA=="],"p":[6,7,6,0,5,"eTRTeQQA"],"q":[6,7,6,0,5,"eSQSeAAA"],"r":[5,5,4,0,5,"chCEAA=="],"s":[5,5,5,0,5,"chwXAA=="],"t":[4,7,4,0,3,"RPREcA=="],"u":[6,5,6,0,5,"QQQSeA=="],"v":[6,5,6,0,5,"iSSMMA=="],"w":[8,5,8,0,5,"GVpSZiQ="],"x":[6,5,6,0,5,"SMMcSA=="],"y":[6,7,6,0,5,"CSQMMIYA"],"z":[5,5,5,0,5,"eIiPgA=="],"0":[6,7,6,0,3,"OSRRRSOA"],"1":[6,7,6,0,3,"cEEEEEeA"],"2":[6,7,6,0,3,"OSCCMQeA"],"3":[6,7,6,0,3,"OSCOCCeA"],"4":[6,7,6,0,3,"GKCS/CCA"],"5":[6,7,6,0,3,"eQcCCCcA"],"6":[6,7,6,0,3,"OYQeTTOA"],"7":[6,7,6,0,3,"eCCEEIIA"],"8":[6,7,6,0,3,"OSSOTTeA"],"9":[6,7,6,0,3,"cSTfDCcA"]," ":[3,0,3,0,10,""],".":[3,1,3,0,9,"QA=="],",":[3,2,3,0,9,"SA=="],"-":[4,3,4,0,7,"4AA="],"/":[4,8,3,0,3,"IiREiA=="],"(":[4,9,4,0,2,"IEREQCA="],")":[4,9,4,0,2,"RCIiIEA="],"'":[3,7,3,0,3,"SQAA"],"\"":[5,7,5,0,3,"UpQAAAA="],":":[3,5,3,0,5,"QAQ="],";":[3,6,3,0,5,"QASA"],"+":[8,7,8,0,3,"CAgIfggICA=="],"=":[8,5,8,0,5,"fgB+AAA="],"<":[8,6,8,0,4,"AhhgGAIA"],">":[8,6,8,0,4,"YBgGGGAA"],"•":[6,5,6,0,5,"MMMAAA=="],"—":[10,3,10,0,7,"/8AAAA=="],"–":[5,3,5,0,7,"+AA="],"&":[8,7,8,0,3,"MCggUkpEOg=="],"!":[4,7,4,0,3,"IiAAIA=="],"?":[5,7,5,0,3,"cMRCAIA="],"%":[10,7,10,0,3,"YhQFQawChKIw"],"#":[8,7,8,0,3,"EBR/BH4oKA=="],"Š":[6,9,6,0,1,"MAeQQOBDeA=="],"Ž":[7,9,7,0,1,"EAHwIIIIIPw="],"Č":[7,9,7,0,1,"GADzBAgQMDw="],"Ć":[7,9,7,0,1,"CADzBAgQMDw="],"Đ":[8,7,8,0,3,"fEZC8kJGfA=="],"š":[5,8,5,0,2,"UQDkOC4="],"ž":[5,8,5,0,2,"UQDxER8="],"č":[6,8,6,0,2,"IEAOQQQO"],"ć":[6,8,6,0,2,"AEAOQQQO"],"đ":[7,8,6,0,2,"ADgDxIgSPA=="]},"r12":{"A":[9,9,8,0,3,"GAwFBIJDEfiGwQA="],"B":[8,9,8,0,3,"fEZCRnxCQkJ8"],"C":[8,9,8,0,3,"HiFAQEBAQCEe"],"D":[9,9,9,0,3,"fCGQSCQaCQSGfAA="],"E":[8,9,8,0,3,"fkBAQH5AQEB+"],"F":[7,9,7,0,3,"fIECB8gQIEA="],"G":[9,9,9,0,3,"HhCQCARyCQRCHgA="],"H":[9,9,9,0,3,"QSCQSCfyCQSCQQA="],"I":[4,9,4,0,3,"REREREA="],"J":[5,11,4,-1,3,"IQhCEIQhMA=="],"K":[9,9,8,0,3,"QiISDgcCwTCMQwA="],"L":[7,9,7,0,3,"QIECBAgQIH4="],"M":[10,9,10,0,3,"YZxlKUpKkyTJAkCA"],"N":[9,9,9,0,3,"YTiUSySSaRSOQwA="],"O":[9,9,9,0,3,"HhGQSDQaDQRGHgA="],"P":[7,9,7,0,3,"fI0KN8gQIEA="],"Q":[9,11,9,0,3,"HhGQSDQaDQRGHgEAwA=="],"R":[8,9,8,0,3,"fEZCRnxEQkJD"],"S":[8,9,8,0,3,"PEBAYDwGAkY8"],"T":[9,9,7,-1,3,"fwQCAQCAQCAQCAA="],"U":[9,9,9,0,3,"QSCQSCQSCQxEHAA="],"V":[9,9,8,0,3,"wSGQjEJBIFAwGAA="],"W":[12,9,12,0,3,"RiRiRiSmaUKUKUMcMIA="],"X":[8,9,8,0,3,"QiY0GBgcJGJD"],"Y":[9,9,7,-1,3,"YREFg4CAQCAQCAA="],"Z":[8,9,8,0,3,"fwIEDBgQIEB/"],"a":[7,7,7,0,5,"eAgR5EifAA=="],"b":[8,10,8,0,2,"QEBAXGRCQkJkXA=="],"c":[7,7,7,0,5,"OMkCBAyOAA=="],"d":[8,10,8,0,2,"BgYGPmZGRkZmPg=="],"e":[7,7,7,0,5,"OMkL9AwPAA=="],"f":[5,10,4,0,2,"MxHkIQhCAA=="],"g":[8,10,8,0,5,"PkZGRkZGPgQEOA=="],"h":[8,10,8,0,2,"QEBAXGRGQkJCQg=="],"i":[3,9,3,0,3,"QSSSQA=="],"j":[4,12,3,-1,3,"ICIiIiIm"],"k":[7,10,7,0,2,"QIECJIocKEiI"],"l":[3,10,3,0,2,"SSSSSA=="],"m":[12,7,12,0,5,"fcZkRCRCRCRCRCA="],"n":[8,7,8,0,5,"XGRGQkJCQg=="],"o":[7,7,7,0,5,"OMkaFGyOAA=="],"p":[8,10,8,0,5,"XGRCQkJkXEBAQA=="],"q":[8,10,8,0,5,"PmZGRkZmPgYGBg=="],"r":[5,7,5,0,5,"WxCEIQA="],"s":[6,7,6,0,5,"eQQMDDeA"],"t":[5,9,5,0,3,"QjyEIQgw"],"u":[8,7,8,0,5,"RkZGRkZmPg=="],"v":[7,7,7,0,5,"RokRYocEAA=="],"w":[10,7,10,0,5,"TJMkyVQzDMMw"],"x":[7,7,7,0,5,"RFjgg42RAA=="],"y":[7,10,7,0,5,"RokRQocECDDA"],"z":[6,7,6,0,5,"fCGEIQfA"],"0":[8,9,8,0,3,"OGRGQkJCRmQ4"],"1":[8,9,8,0,3,"eBgYGBgYGBh+"],"2":[8,9,8,0,3,"OEQEBAwYMGB8"],"3":[8,9,8,0,3,"OEQEBDgEBkQ4"],"4":[8,9,8,0,3,"DBwUJEREfgQE"],"5":[8,9,8,0,3,"fEBAeAQGBkQ4"],"6":[8,9,8,0,3,"HCBAXGZCQmQ8"],"7":[8,9,8,0,3,"fgQECAgIEBAw"],"8":[8,9,8,0,3,"PGRGZDxEQkY8"],"9":[8,9,8,0,3,"OGRGRmY+BAQ4"]," ":[4,0,4,0,12,""],".":[4,2,4,0,10,"Zg=="],",":[4,3,4,0,10,"ZEA="],"-":[4,4,4,0,8,"cAA="],"/":[5,10,4,0,3,"EIhCIQiEAA=="],"(":[5,11,5,0,2,"AQiEIQghAA=="],")":[5,11,5,0,2,"QQhDGMQhEA=="],"'":[3,9,3,0,3,"SQAAAA=="],"\"":[6,9,6,0,3,"UUUAAAAAAA=="],":":[4,'''
r'''6,4,0,6,"ZgBm"],";":[4,7,4,0,6,"ZgBkQA=="],"+":[10,7,10,0,5,"BAEAQf4EAQBA"],"=":[10,5,10,0,7,"f4AH+AAAAA=="],"<":[10,7,10,0,5,"AYODAMAOAGAA"],">":[10,7,10,0,5,"YAcAMAwcGAAA"],"•":[7,6,7,0,6,"OHDgAAAA"],"—":[12,4,12,0,8,"f+AAAAAA"],"–":[6,4,6,0,8,"eAAA"],"&":[9,9,9,0,3,"GBIIBgWSaRzGPYA="],"!":[5,9,5,0,3,"IQhCEAQg"],"?":[6,9,6,0,3,"OSCGEIAIIA=="],"%":[11,9,11,0,3,"cIshKC0HTArCSIsQwA=="],"#":[10,8,10,0,4,"CQID+EgSH8FAkA=="],"Š":[8,11,8,0,1,"KBg8QEBgPAYCRjw="],"Ž":[8,11,8,0,1,"BBh/AgQMGBAgQH8="],"Č":[8,11,8,0,1,"FAweIUBAQEBAIR4="],"Ć":[8,11,8,0,1,"BAgeIUBAQEBAIR4="],"Đ":[9,9,9,0,3,"fCGQSD8aDQSGfAA="],"š":[6,10,6,0,2,"KMAeQQMDDeA="],"ž":[6,10,6,0,2,"KMAfCGEIQfA="],"č":[7,10,7,0,2,"KDABxkgQIGRw"],"ć":[7,10,7,0,2,"CCABxkgQIGRw"],"đ":[8,10,8,0,2,"Bg4GPmZGRkZmPg=="]},"b14":{"A":[11,10,11,0,3,"DgPgfA2DuGMf4wZg3Bw="],"B":[11,10,11,0,3,"fw5xxjnH8OMcc45xj+A="],"C":[10,10,10,0,3,"D44nAcBgGAcBwDgD4A=="],"D":[12,10,12,0,3,"fwcYcMcOcOcOcOcMcYfw"],"E":[10,10,10,0,3,"fxwHAcB/HAcBwHAf4A=="],"F":[10,10,10,0,3,"fxwHAcB/HAcBwHAcAA=="],"G":[11,10,11,0,3,"D8cJwDgGPMGcM4Y4wfg="],"H":[12,10,12,0,3,"cMcMcMcMf8cMcMcMcMcM"],"I":[5,10,5,0,3,"c5znOc5zgA=="],"J":[6,13,5,-1,3,"OOOOOOOOOOOO4A=="],"K":[12,10,11,0,3,"ccc4dwfgfAfgfwd4c8ce"],"L":[9,10,9,0,3,"cDgcDgcDgcDgcD/A"],"M":[14,10,14,0,3,"eHnh58+fPne53udznM5wOcDg"],"N":[12,10,12,0,3,"cMeMfMfMdsdsc8c8cccc"],"O":[12,10,12,0,3,"H4OccOcOYOYOcOcOOcH4"],"P":[10,10,10,0,3,"fxznHcdx3OfxwHAcAA=="],"Q":[12,12,12,0,3,"HwOccOcOYOYOcOcOOcH4AYAc"],"R":[11,10,11,0,3,"fw5xxjjHOP4c44xxzjg="],"S":[10,10,10,0,3,"HxxGAcB/D+B4DkOfwA=="],"T":[10,10,10,0,3,"/4cBwHAcBwHAcBwHAA=="],"U":[11,10,11,0,3,"cc45xzjnHOOcc445w+A="],"V":[11,10,11,0,3,"4OwZxzjDOHcGwPgfAcA="],"W":[15,10,15,0,3,"Y47HHc8zlmNtxtuPnh48PHg48A=="],"X":[11,10,11,0,3,"cc4w7g+A4DwHwdxxjDg="],"Y":[12,10,10,-1,3,"cOOcGcH4DwBwBgBgBgBg"],"Z":[10,10,10,0,3,"f4DgeDweB4PB4HAf8A=="],"a":[9,8,9,0,5,"fgOAx+YzGZx2"],"b":[10,11,10,0,2,"cBwHAfxznGcZxnGc5/A="],"c":[8,8,8,0,5,"HnBgYGBgcB4="],"d":[10,11,10,0,2,"A4DgOP5zmOY5jmOc4/g="],"e":[10,8,10,0,5,"HhzGOf5gGAcQeA=="],"f":[7,11,6,0,2,"PGHH5w4cOHDhwA=="],"g":[10,11,10,0,5,"P5zmOY5jmOc4/gOAw+A="],"h":[10,11,10,0,2,"cBwHAfxznOc5znOc5zg="],"i":[5,11,5,0,2,"c4DnOc5znA=="],"j":[6,14,5,-1,2,"OOAOOOOOOOOOMcA="],"k":[10,11,9,0,2,"cBwHAc53H4fB8H4dxzg="],"l":[5,11,5,0,2,"c5znOc5znA=="],"m":[15,8,15,0,5,"f3DnMc5jnMc5jnMc5jnM"],"n":[10,8,10,0,5,"fxznOc5znOc5zg=="],"o":[10,8,10,0,5,"HhzGOY5jmOcweA=="],"p":[10,11,10,0,5,"fxznGcZxnGc5/HAcBwA="],"q":[10,11,10,0,5,"P5zmOY5jmOc4/gOA4Dg="],"r":[7,8,7,0,5,"fuHDhw4cOA=="],"s":[8,8,8,0,5,"PGJgfj4HRjw="],"t":[7,10,7,0,3,"cOPzhw4cODB4"],"u":[10,8,10,0,5,"c5znOc5znOc4/g=="],"v":[9,8,9,0,5,"47GcxuNh8HA4"],"w":[13,8,13,0,5,"ZzM5mdzu494e8PeHHA=="],"x":[9,8,9,0,5,"YzuPg4HB8dzG"],"y":[9,11,9,0,5,"47GcxuNh8Hg4HAweAA=="],"z":[8,8,8,0,5,"fg4eHDh4cH4="],"0":[10,10,10,0,3,"HgzGOY5jmOY5jjMHgA=="],"1":[10,10,10,0,3,"HAsAwDAMAwDAMAwP4A=="],"2":[10,10,10,0,3,"PhHAMAwHA4HA4DAf4A=="],"3":[10,10,10,0,3,"PhHAMBweAcA4DkcPgA=="],"4":[10,10,10,0,3,"DwPB8NxnGcf4HAcBwA=="],"5":[10,10,10,0,3,"fxwHAfgHAOA4DkcPgA=="],"6":[10,10,10,0,3,"HgwHAfhzHOc5zjMHgA=="],"7":[10,10,10,0,3,"f4DgcBwOA4DAcBgOAA=="],"8":[10,10,10,0,3,"PhzHOcw+HMY5jnMPgA=="],"9":[10,10,10,0,3,"HhzGMY5jnOP4DAcPAA=="]," ":[5,0,5,0,13,""],".":[5,3,5,0,10,"c5w="],",":[5,5,5,0,10,"c5zGAA=="],"-":[6,5,6,0,8,"eeAAAA=="],"/":[6,12,5,0,3,"GGEEMIIYYQww"],"(":[6,12,6,0,2,"GOMMccccMMOG"],")":[6,12,6,0,2,"YMMGGGGGGMMY"],"'":[4,10,4,0,3,"ZmYAAAA="],"\"":[7,10,7,0,3,"bNmzYAAAAAAA"],":":[6,8,6,0,5,"MMMAAMMM"],";":[6,10,6,0,5,"MMMAAMMcYYA="],"+":[12,8,12,0,5,"BgBgBgf8f8BgBgBg"],"=":[12,8,12,0,5,"f8f8AAAAf8f8AAAA"],"<":[12,8,12,0,5,"AEA8HwOAOAHwA8AE"],">":[12,8,12,0,5,"IAPADwAcAcDwPAIA"],"•":[9,8,9,0,5,"HB8Ph8HAAAAA"],"—":[14,5,14,0,8,"f/n/4AAAAAAA"],"–":[7,5,7,0,8,"fPgAAAA="],"&":[12,10,12,0,3,"DgGQOAHAPGfmZ+Y8c8H+"],"!":[6,10,6,0,3,"MMMMMMMAMMA="],"?":[8,10,8,0,3,"PE4GDhwYOAA4OA=="],"%":[14,10,14,0,3,"OGGzBMgTYG1w6yBswTMMyGHA"],"#":[12,10,12,0,3,"BIDIDYP+CQGQf8EwEgMg"],"Š":[10,14,10,0,-1,"EgcAAAAfHEYBwH8P4HgOQ5/A"],"Ž":[10,14,10,0,-1,"EgcAAAB/gOB4PB4Hg8HgcB/w"],"Č":[10,14,10,0,-1,"CQGAAAAPjicBwGAYBwHAOAPg"],"Ć":[10,14,10,0,-1,"AwGAAAAPjicBwGAYBwHAOAPg"],"Đ":[12,10,12,0,3,"fwcccMcOcO/OcOcMccfw"],"š":[8,11,8,0,2,"JDwYPGJgfj4HRjw="],"ž":[8,11,8,0,2,"JDwYfg4eHDh4cH4="],"č":[8,11,8,0,2,"Eh4MHnBgYGBgcB4="],"ć":[8,11,8,0,2,"AgYMHnBgYGBgcB4="],"đ":[10,11,10,0,2,"A4PwOP5zmOY5jmOc4/g="]},"b16":{"A":[13,12,12,0,3,"DwB8A+A/Adwc4OcHHH/j/xwdwOA="],"B":[12,12,12,0,3,"f4f8cccOccf8f8cOcOcOf+f4"],"C":[12,12,12,0,3,"D8H+PCeAcAcAcAcAeAPCH+D8"],"D":[13,12,13,0,3,"f4P/HDjg5wc4OcHODnBzhx/4/wA="],"E":[11,12,11,0,3,"f8/5wDgHAP8f44BwDgH/P+A="],"F":[11,12,11,0,3,"f8/5wDgHAP8f44BwDgHAOAA="],"G":[13,12,13,0,3,"D+D/jwjwBwA4AcfOPnhx44f8H4A="],"H":[13,12,13,0,3,"cHODnBzg5wc/+f/ODnBzg5wc4OA="],"I":[6,12,6,0,3,"cccccccccccc"],"J":[7,15,6,-1,3,"OHDhw4cOHDhw4cOfOAA="],"K":[13,12,12,0,3,"cPOPHPDvB/A/AfgP4HODjhw44OA="],"L":[10,12,10,0,3,"cBwHAcBwHAcBwHAcB/3/"],"M":[16,12,16,0,3,"eDx8PHw8fnx+fHfsc8xzzHP'''
r'''McYxwDHAM"],"N":[13,12,13,0,3,"eHPjnxz85+c7uc3OfnHzj5w84eA="],"O":[14,12,14,0,3,"D4B/g48cHHA5wOcDnA5wcOPB/gPg"],"P":[12,12,12,0,3,"f4f8cecOcOcef8f4cAcAcAcA"],"Q":[14,14,14,0,3,"D8B/g48cHHA5wOcDnA5wcOPB/gPwAMABgA=="],"R":[12,12,12,0,3,"f4f8ccccccf4f4cccccOcOcH"],"S":[12,12,12,0,3,"H4P8cMcAeAP4H8A8AcYcf8Pw"],"T":[11,12,11,0,3,"///8OAcA4BwDgHAOAcA4BwA="],"U":[13,12,13,0,3,"cHODnBzg5wc4OcHPHjjhxw/4HwA="],"V":[13,12,12,0,3,"4HODnDjhw44c4OcDuB+AfAPgHgA="],"W":[18,12,18,0,3,"YcOceOceOcecM2cO3cOzcOzYPz4Hj4Hh4Hh4"],"X":[13,12,12,0,3,"cPPHDnA/gfgHgDwD8B3Bzhw44OA="],"Y":[13,12,12,-1,3,"cHHDjzg7wPwHwB4A4AcAOAHADgA="],"Z":[12,12,12,0,3,"f+f+AcA4B4DwHgHAPAeAf+f+"],"a":[11,9,11,0,6,"fw/wBh/n/OOc8/49wA=="],"b":[11,12,11,0,3,"cA4BwDvH/POcO4dw7zn/O8A="],"c":[9,9,9,0,6,"Hx+eDgcDgeB+HwA="],"d":[11,12,11,0,3,"AcA4Bw/j/OOcc45xzjj/D+A="],"e":[11,9,11,0,6,"Hwfxxz/n/OAcMf4fAA=="],"f":[8,12,7,0,3,"Hj44/v44ODg4ODg4"],"g":[11,12,11,0,6,"H8f5xzjnHOOccf4fxDj+D4A="],"h":[11,12,11,0,3,"cA4BwDvH/POcc45xzjnHOOA="],"i":[5,12,5,0,3,"c4DnOc5znOA="],"j":[6,15,5,-1,3,"OOAOOOOOOOOOO+8A"],"k":[11,12,11,0,3,"cA4BwDjnOO4fg/B/DvHPOOA="],"l":[5,12,5,0,3,"c5znOc5znOA="],"m":[17,9,17,0,6,"d7w//x5zjjjHHGOOMccY44xxxgA="],"n":[11,9,11,0,6,"d4/55zjnHOOcc45xwA=="],"o":[11,9,11,0,6,"HwfxxzjnHOOccfwfAA=="],"p":[11,12,11,0,6,"d4/55zh3DuHec/53jgHAOAA="],"q":[11,12,11,0,6,"H8f5xzjnHOOccf4fwDgHAOA="],"r":[8,9,8,0,6,"d394cHBwcHBw"],"s":[10,9,10,0,6,"Ph/HEcA/AOQ5/D4A"],"t":[8,11,8,0,4,"MDD+/jAwMDA4Ph4="],"u":[11,9,11,0,6,"cc45xzjnHOOc8f4dwA=="],"v":[11,9,10,0,6,"4c45xhnDsH4HwPAeAA=="],"w":[15,9,15,0,6,"Y5znOc5zvMNvh98Pvh44HHA="],"x":[11,9,10,0,6,"cc5w/A8B4D4Pw5xxwA=="],"y":[11,12,10,0,6,"4c45xhnDsD4HwPAOAYDwHAA="],"z":[9,9,9,0,6,"f7/BwcHBwcD/f4A="],"0":[11,12,11,0,3,"Hwfx5zjnHOOcc45xzzj+D4A="],"1":[11,12,11,0,3,"HgfAuAMAYAwBgDAGAMD/H+A="],"2":[11,12,11,0,3,"Hw/xDwDgPAcBwHAcBwH/P+A="],"3":[11,12,11,0,3,"HwfwjwHB8D8A8A4ByHn+H4A="],"4":[11,12,11,0,3,"B4HwPg3BuGcc4xx/z/gOAcA="],"5":[11,12,11,0,3,"P4fwwBgD8H8I8A4ByHn+D4A="],"6":[11,12,11,0,3,"D4P44DgH8P+ec45xxzj+B4A="],"7":[11,12,11,0,3,"f8/4DwHAOA4BwHAOA4BwDgA="],"8":[11,12,11,0,3,"Hwf5xzjj+H8cc45xzjj+D4A="],"9":[11,12,11,0,3,"HwfxzjjnHOeP8P4BxHD8DwA="]," ":[6,0,6,0,15,""],".":[6,3,6,0,12,"MMMA"],",":[6,5,6,0,12,"MMMcYA=="],"-":[7,6,7,0,9,"fPgAAAAA"],"/":[6,13,6,0,3,"DCGGEMMIYYYwwA=="],"(":[7,14,7,0,3,"HDDhwwYcODBg4cGDgA=="],")":[7,14,7,0,3,"MGDgwcOHDhw4YcMGAA=="],"'":[5,12,5,0,3,"IQhAAAAAAAA="],"\"":[8,12,8,0,3,"JiYmJgAAAAAAAAAA"],":":[6,9,6,0,6,"OOOAAAOOOA=="],";":[6,11,6,0,6,"OOOAAAOOMcYA"],"+":[13,10,13,0,5,"AwAYAMAGA/8f+AwAYAMAGAA="],"=":[13,8,13,0,7,"P/H/gAAAA/8f+AAAAA=="],"<":[13,10,13,0,5,"ADAHgfB8A4AfAB8AHgAwAAA="],">":[13,10,13,0,5,"IAHgB+AHwA8B8H4HgCAAAAA="],"•":[10,9,10,0,6,"DgeD8PweA4AAAAAA"],"—":[16,6,16,0,9,"f/5//gAAAAAAAAAA"],"–":[8,6,8,0,9,"fn4AAAAA"],"&":[14,12,14,0,3,"DwB+AcAHABwA+OdzHPxx8eeD/wfO"],"!":[7,12,7,0,3,"OHDhw4cODABw4cA="],"?":[9,12,9,0,3,"Pj+RwOBwcHA4AA4HA4A="],"%":[16,12,16,0,3,"ODBsMGZgZkBswDmAAZwDNgJiBmIMNgwc"],"#":[13,12,13,0,3,"BmAzARB/4/8GYDIP/H/gzAZAJgA="],"Š":[12,15,12,0,0,"GwDgAAH4P8cMcAeAP4H8A8AcYcf8PwA="],"Ž":[12,15,12,0,0,"GQDgAAf+f+AcA4B4DwHgHAPAeAf+f+A="],"Č":[12,15,12,0,0,"DIBwAAD8H+PCeAcAcAcAcAeAPCH+D8A="],"Ć":[12,15,12,0,0,"AYAwAAD8H+PCeAcAcAcAcAeAPCH+D8A="],"Đ":[13,12,13,0,3,"P4H/Djxw44d+P/HnDjhxx4/4fwA="],"š":[10,13,10,0,2,"MgeBwAA+H8cRwD8A5Dn8PgA="],"ž":[9,13,9,0,2,"Mg8HAAf7/BwcHBwcD/f4"],"č":[9,13,9,0,2,"GQeDgAHx+eDgcDgeB+Hw"],"ć":[9,13,9,0,2,"AwEBgAHx+eDgcDgeB+Hw"],"đ":[12,12,11,0,3,"AcB+AcH8P8ccccccccccP8H8"]},"b30":{"A":[24,22,23,0,6,"AP4AAP8AAf8AAf8AAf+AA/+AA++AB+/AB8fAB8fAD8fgD4PgD4PwH4PwH//wH//4P//4P//4fgD8fgB8fAB+/AB+"],"B":[23,22,23,0,6,"H/8AP/+Af/+A//8B8H8D4H4HwPwPgfgfB+A//8B//gD//gH//wPgfgfAfg+A/B8B+D4H8H//wP//gf/+A//gAA=="],"C":[22,22,22,0,6,"AH+AB//Af/8D//wf4HB+AEP4AA/AAD8AAPgAA+AAD4AAPgAA/AAD8AAP4AAfgBB/gcD//wH//AH/8AH+AA=="],"D":[25,22,25,0,6,"H/4AD//gB//8A///AfA/gPgP4HwD+D4A/B8Afg+APwfAH4PgD8HwB+D4A/B8Afg+AfwfAfwPgfwH//4D//wB//wA//AA"],"E":[21,22,20,0,6,"H//A//4H//A//4HwAA+AAHwAA+AAHwAA//wH/+A//wH/+A+AAHwAA+AAHwAA+AAH//A//4H//A//4A=="],"F":[21,22,20,0,6,"H//A//4H//A//4HwAA+AAHwAA+AAHwAA//wH/+A//wH/+A+AAHwAA+AAHwAA+AAHwAA+AAHwAA+AAA=="],"G":[25,22,25,0,6,"AD/AAP/8Af//Af//gf4DwP4AIP4AAH4AAD8AAB8AAA+A/wfAf4PgP8H4H+D8AfB/APgfgHwP8D4D//8A//+AH/+AA/4A"],"H":[25,22,25,0,6,"HwB8D4A+B8AfA+APgfAHwPgD4HwB8D4A+B8AfA///gf//wP//4H//8D4A+B8AfA+APgfAHwPgD4HwB8D4A+B8AfA+APg"],"I":[11,22,11,0,6,"HwPgfA+B8D4HwPgfA+B8D4HwPgfA+B8D4HwPgfA+AA=="],"J":[13,28,11,-2,6,"B8A+AfAPgHwD4B8A+AfAPgHwD4B8A+AfAPgHwD4B8A+AfAPgPwP4/4f8P4HwAA=="],"K":[25,22,23,0,6,"HwD+D4D+B8D+A+D+AfD+APj+AHz+AD/+AB/8AA/8AAf+AAP/gAH/4AD/+AB8/gA+P4AfD+APg/gHwP4D4D+B8A/g+AP4"],"L":[19,22,19,0,6,"HwAD4AB8AA+AAfAAPgAHwAD4AB8AA+AAfAAPgAHwAD4AB8AA+AAfAAPgAH//D//h//w//4A="],"M":[30,22,30,0,6,"H8AP4H+Af4H+Af4H+A/4H/A/4H/A/4H/h/4H3h74H3j74Hzzz4Hzzz4Hz/j4Hx/j4Hx/j4Hw/D4Hw/D4HweD4HweD4HwAD4HwAD4HwAD4HwAD4A="],"N":[25,22,25,0,6,"H4B8D+A+B/AfA/wPgf4HwP+D4H/B8D/w+B98fA++PgfPnwPjz4Hx98D4e+B8P/A+D/gfB/wPgf4HwP8D4D+B8B/A+Afg'''
r'''"],"O":[26,22,26,0,6,"AH+AAP/4AH//AD//4B/B/AfgP4PwB+D8APw/AD8PgA/D4APw+AD8PgA/D8APw/AD8PwB+B+A/gfwfwD//4Af/8AD/+AAH+AA"],"P":[22,22,22,0,6,"H/8Af/8B//4H//wfA/B8B+HwH4fAfh8B+HwPwf//B//4H//Af/wB8AAHwAAfAAB8AAHwAAfAAB8AAHwAAA=="],"Q":[26,26,26,0,6,"AH+AAP/4AH//gD//8B/B/AfgP4PwB+D8APw/AD8PgA/D4APw+AD8PgA/D8APw/AD8PwB+B+A/gfwfwD//4Af/8AD/+AAH/AAAD4AAAfAAAD4AAA/AA=="],"R":[23,22,23,0,6,"H/4AP/+Af/+A//8B8H8D4H4HwPwPgfgfA+A+D8B//wD//AH/+AP/+AfD+A+D8B8D8D4H4HwH4PgPwfAPw+AfgA=="],"S":[22,22,22,0,6,"Af4AH/8A//wH//A/A8D8AQPgAA/AAD+AAH/wAf/4Af/wAf/gAH+AAH4AAPgwA+DwH4P//g//8B//gA/4AA=="],"T":[21,22,20,0,6,"///3//+///3//+AfgAD8AAfgAD8AAfgAD8AAfgAD8AAfgAD8AAfgAD8AAfgAD8AAfgAD8AAfgAD8AA=="],"U":[24,22,24,0,6,"HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8HwD8H4D4H4H4D8P4D//wB//gA//AAP8A"],"V":[24,22,23,0,6,"/AB+fAB+fgB8fgD8PgD4PwH4HwH4HwHwH4PwD4PwD8PgD8fgB8fAB+fAB+/AA++AA/+AAf+AAf8AAf8AAP8AAP4A"],"W":[33,22,33,0,6,"fAPgHz8D+B+fgfwPx8D+B8PgfwPh+D/D8Pw94fg+HvD4Hw94fA/HnD4H548/AfPHnwD548+AfPHnwD/wf+AP+D/wB/wf8AP+D/gB/gP8AP8B/gA/gP4AH8B/AA=="],"X":[23,22,23,0,6,"fgD8fgPwfAfg/B+A/H4A+PwB+/AB/8AB/wAD/gAD+AAH8AAf8AB/8AD/4AP34A/H4B+HwH4PwfgPw+APz8AfgA=="],"Y":[24,22,22,-1,6,"fgB+PwD8PwH4H4H4D8PwD8fgB+fgA//AA/+AAf+AAP8AAP4AAH4AAH4AAH4AAH4AAH4AAH4AAH4AAH4AAH4AAH4A"],"Z":[22,22,22,0,6,"P//w///D//8P//wAB+AAPwAB/AAP4AB/AAH4AA/AAH8AA/gAH8AAfgAD8AAfwAD+AAf//x///H//8f//wA=="],"a":[20,16,20,0,12,"H/wB//Af/4GA+AAHwH/8H//D//w/B8fgfH4Px+D8Px/D//wf58D8fA=="],"b":[21,23,21,0,5,"HwAA+AAHwAA+AAHwAA+AAHwAA+PgH3+A//4H8fg/B8HwPw+A+HwHw+A+HwHw+B+H4Pg/j8H//A+/wHx8AA=="],"c":[18,16,18,0,12,"AfwB/8H/8H4MPwEPgAfgAfgAfgAfgAPgAPwEH4MH/8B/8Afw"],"d":[21,23,21,0,5,"AAPgAB8AAPgAB8AAPgAB8AAPgHx8D/Pg//8P4/h+D8Pgfj8B8fgPj8B8fgPh8D8Pwfh/H8H//gf58A+PgA=="],"e":[20,16,20,0,12,"AfwAf/Af/4H4+D8Hw+B8fgfn//5//+f//j4AA+AEH4HB//wH/8Af8A=="],"f":[14,23,13,0,5,"A/gf4P+H4B+AfAHwH/5/+f/h8AfAHwB8AfAHwB8AfAHwB8AfAHwB8AA="],"g":[21,22,21,0,12,"A+Pgf58H//h/H8Pwfh8D8fgPj8B8fgPj8B8Pgfh+D8Pw/g//8D/PgHx8AAfggD4HB/A//wH/8AP8AA=="],"h":[21,23,21,0,5,"HwAA+AAHwAA+AAHwAA+AAHwAA+PgH3+A//4H8fg/D8HwPg+B8HwPg+B8HwPg+B8HwPg+B8HwPg+B8HwPgA=="],"i":[10,23,10,0,5,"HwfB8HwfAAAAfB8HwfB8HwfB8HwfB8HwfB8HwfA="],"j":[11,29,10,-1,5,"D4HwPgfA+AAAAHwPgfA+B8D4HwPgfA+B8D4HwPgfA+D8H4Pj/H8PgA=="],"k":[21,23,20,0,5,"HwAA+AAHwAA+AAHwAA+AAHwAA+D8Hw/A+PwHz8A+/AH/wA/8AH/AA/8AH/wA+/AHz8A+PwHw/A+D8HwPwA=="],"l":[10,23,10,0,5,"HwfB8HwfB8HwfB8HwfB8HwfB8HwfB8HwfB8HwfA="],"m":[31,16,31,0,12,"Px4HwH7/P8D//v/B/H+Pw/B+H4fg/B8PwfA+H4PgfD8HwPh+D4Hw/B8D4fg+B8PwfA+H4PgfD8HwPh+D4Hw="],"n":[21,16,21,0,12,"Hx8A+/wH//A/j8H4fg+B8HwPg+B8HwPg+B8HwPg+B8HwPg+B8HwPg+B8"],"o":[21,16,21,0,12,"AfwAP/gH/+A/H4Pwfh8B8fgPj8B8fgPj8B8PgPh+D8H4/A//wB/8AD+A"],"p":[21,22,21,0,12,"Hx8A+/wH//A/j8H4Pg+B+HwHw+A+HwHw+A+HwPw/B8H8fg//4H3+A+PgHwAA+AAHwAA+AAHwAA+AAA=="],"q":[21,22,21,0,12,"A+Pgf58H//h/H8Pwfh8D8fgPj8B8fgPj8B8Pgfh+D8P4/g//8D/PgHx8AAPgAB8AAPgAB8AAPgAB8A=="],"r":[15,16,15,0,12,"Hx4+/H/4//H8I/AHwA+AHwA+AHwA+AHwA+AHwA+A"],"s":[18,16,18,0,12,"B/gH/4P/4Pg4PAIPgAP8AP/wD/8AP8AB8IB8OB8P/8P/4D/g"],"t":[14,21,14,0,7,"HwB8AfAHwB8D//////8fAHwB8AfAHwB8AfAHwB8AfgH/g/4H+A=="],"u":[21,16,21,0,12,"PwPh+B8PwPh+B8PwPh+B8PwPh+B8PwPh+D8Pwfh+D8H4/g//8D/PgPx8"],"v":[20,16,20,0,12,"fAPnwH5+B8PgfD4PgfD4Hx8B8fAPnwD74Af+AH/AB/wAP8AD+AAfgA=="],"w":[28,16,28,0,12,"fA8H5+HwfD4fh8Ph+Hw+H4+B8/j4HzvPgfO8+B853wD/nfAP8f8A/x/wD/D+AH8P4Afg/gB+D8A="],"x":[19,16,19,0,12,"fgfHwfB8fg/PgP/gD/gA/wAfwAP4AP+AH/gH3wH58H4fD4Pz4D8="],"y":[20,22,20,0,12,"fAPnwHx+B8PgfD4PgfD4Hw8A+fAPnwB74Af+AH/AA/wAP8AB+AAfgAD4AB8AAfAB/gAfwAH4AA=="],"z":[17,16,17,0,12,"P/8f/4//wAfgB+AH4AfgB/AH8AfwB/AH8AfwA//5//z//g=="],"0":[21,22,21,0,6,"AfwAP/gD/+A//4H4/B+D8Pwfh8B8PgPh8B8fgPj8B8PgPh8B8PgPh+D8Pwfg/H4H//Af/wB/8AD+AA=="],"1":[21,22,21,0,6,"A/wA/+AH/wA/+AHPwAB+AAPwAB+AAPwAB+AAPwAB+AAPwAB+AAPwAB+AAPwAB+AD//gf/8D//gf/8A=="],"2":[21,22,21,0,6,"B/gB//gP/+B//wPB/AAH4AA/AAH4AA/AAHwAB+AAfgAH4AD+AA/gAPwAD8AA/AAP//B//4P//B//4A=="],"3":[21,22,21,0,6,"B/wA//gH/+A//4GB/AAH4AA/AAH4AB+AH/gA/4AH/gA/+AAP4AAfAAD4IAfBwP4P//B//wH/8AP8AA=="],"4":[21,22,21,0,6,"AD8AA/gAP8AB/gAf8AH/gA98APPgD58AePgHh8B8PgPB8DwPgf//z//+f//z//+AB8AAPgAB8AAPgA=="],"5":[21,22,21,0,6,"H/+A//wH/+A//wHwAA+AAHwAA/+AH/8A//wH//A4P4EA/gAD8AAfgAD8IA/h4P4P//B//wH/8AH8AA=="],"6":[21,22,21,0,6,"AH4AH/wB//Af/4D8HA/AIHwAB8/AP/+B//4P//B/D8Pwfh+B8PwPh+B8Hwfg/D8D//AP/wA/8AB+AA=="],"7":[21,22,21,0,6,"P//B//4P//B//4AA/AAHwAB+AAPwAB8AAfgAD4AA/AAHwAB+AAPgAD8AAfAAH4AA/AAHwAB+AAPgAA=="],"8":[21,22,21,0,6,"A/wAf/wH//A//4P4/B+D8HwfA/H4D/+AP/AB/8A//wH4/B+D8PgPh8B8Pwfh+H8H//A//4D/+AH+AA=="],"9":[21,22,21,0,6,"AfgAP/AD/8A//wPw/B8D4PgfB8D8Pgfh8D8Pw/h//8H//gf/8A/fAAD4EA/A4PwH/+A//gD/wAH4AA=="]," ":[10,0,10,0,28,""],".":[11,6,11,0,22,"HwPgfA+B8D4A"],",":[11,10,11,0,22,"HwPgfA+B8D4HgeA8BwA="],"-":[12,11,12,0,17,"P+P+P+P+AAAAAAAAAAAAAAA="],"/":[11,25,11,0,6,"AOA4BwDgPAcA4DwHAOA8BwDgHAcA4BwHgOAcB4DgHAeA4AA="],"(":[14,27,14,0,5,"AeAPgDwB8AeAPgD4B8AfAHwB8AfAHwB8AfAHwB8AfAHwB8APgD4AeAHwA8APgB4A"],")":[14,27,14,0,5,"HgB8APAD4A+AHwB8AfADwA+APgD4A+APgD4A+APgD4A8AfAHwB8A+APgDwB8AeAA"'''
r'''],"'":[9,22,9,0,6,"HA4HA4HA4HA4AAAAAAAAAAAAAAAAAAAAAA=="],"\"":[16,22,16,0,6,"HHgceBx4HHgceBx4HHgceAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="],":":[12,16,12,0,12,"H4H4H4H4H4H4AAAAAAAAH4H4H4H4H4H4"],";":[12,20,12,0,12,"H4H4H4H4H4H4AAAAAAAAH4H4H4H4H4HwHgHgPAOA"],"+":[25,19,25,0,9,"ABwAAA4AAAcAAAOAAAHAAADgAABwAAA4AB///A///gf//wADgAABwAAA4AAAcAAAOAAAHAAADgAABwAA"],"=":[25,14,25,0,14,"H//8D//+B///AAAAAAAAAAAAAH//8D//+B///AAAAAAAAAAAAAAAAAAAAAA="],"<":[25,18,25,0,10,"AAAEAAAeAAB/AAH/gAf/AA/8AD/wAD/AAB+AAA/wAAP/AAA/8AAH/gAAf+AAB/AAAHgAAAQAAAAA"],">":[25,18,25,0,10,"GAAADwAAB/AAA/8AAD/wAAP+AAB/4AAH+AAAfAAB/gAD/gAP+AA/8AD/wAB/AAA8AAAYAAAAAAAA"],"•":[19,16,19,0,12,"AfAAfwAf8AP+AP/gH/wD/4A/4Af8AH8AB8AAAAAAAAAAAAAAAAA="],"—":[30,11,30,0,17,"P///8P///8P///8P///8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"],"–":[15,11,15,0,17,"P/h/8P/h/8AAAAAAAAAAAAAAAAAA"],"&":[26,22,26,0,6,"AH8AAH/wAD/8AB+HAAfAQAHwAAB+AAAPwAAD8AAB/gfA/8Hwf/h8Pz8eD4fvg+D/4Pgf8D4H+A/A/gH4f4A///AH//4Af4/A"],"!":[14,22,14,0,6,"D4A+APgD4A+APgD4A+APgD4A+AHgB4AeAHgAAAAAPgD4A+APgD4A"],"?":[17,22,17,0,6,"P/Af/g//hw/CA+AB8AD4APwA/gD+AH4AfgB+AD8AHwAAAAAAA+AB8AD4AHwAPgA="],"%":[30,22,30,0,6,"D4AOAH+AeAPPAcAeHA4AeHh4AeHhwAeHjgAeHjgAeHHAAPPPAAH+OHwD4cf4AA888AA44eABw4eABx4eADh4eAHg4eAHA4eAOA88AOAf4AcAHwA="],"#":[25,22,25,0,6,"ADhwABw4AB4cAA8eAAcOAAOHAD//+B///A///gBw4AB4cAA4eAAcOAH//8D//+B///ADhwABw4AA4cAA8eAAcOAAOHAA"],"Š":[22,27,22,0,1,"BwcADjgAH8AAPgAAAAAH+AB//AP/8B//wPwPA/AED4AAPwAA/gAB/8AH/+AH/8AH/4AB/gAB+AAD4MAPg8B+D//4P//Af/4AP+AA"],"Ž":[22,27,22,0,1,"BwcADjgAH8AAPgAAAAD//8P//w///D//8AAfgAD8AAfwAD+AAfwAB+AAPwAB/AAP4AB/AAH4AA/AAH8AA/gAH//8f//x///H//8A"],"Č":[22,27,22,0,1,"AMHAA84AB/AAD4AAAAAB/gAf/wH//A//8H+BwfgBD+AAPwAA/AAD4AAPgAA+AAD4AAPwAA/AAD+AAH4AQf4HA//8B//wB//AB/gA"],"Ć":[22,27,22,0,1,"AAeAADwAAOAABwAAAAAB/gAf/wH//A//8H+BwfgBD+AAPwAA/AAD4AAPgAA+AAD4AAPwAA/AAD+AAH4AQf4HA//8B//wB//AB/gA"],"Đ":[25,22,25,0,6,"H/4AD//gB//8A///Afg/wPwH4H4B+D8A/B+Afn/4Hz/8D9/+B+//A+D8A/B+Afg/APwfgPwPwf4H//4D//4B//wA//AA"],"š":[18,24,18,0,4,"DBwDhgBzgB/AA/AAeAAAAAAAB/gH/4P/4Pg4PAIPgAP8AP/wD/8AP8AB8IB8OB8P/8P/4D/g"],"ž":[17,24,17,0,4,"DBwHHAHOAP4APgAPAAAAAAA//x//j//AB+AH4AfgB+AH8AfwB/AH8AfwB/AD//n//P/+"],"č":[18,24,18,0,4,"BwcA44Ad4AfwAPgAHgAAAAAAAfwB/8H/8H4MPwEPgAfgAfgAfgAfgAPgAPwEH4MH/8B/8Afw"],"ć":[18,24,18,0,4,"AA8AA4ABwADwAHgAHAAAAAAAAfwB/8H/8H4MPwEPgAfgAfgAfgAfgAPgAPwEH4MH/8B/8Afw"],"đ":[22,23,21,0,5,"AAPgAA+AAD4AH/4Af/gB/+AAPgD4+A/z4H//g/j+D8H4Pgfh+A+H4D4fgPh+A+D4H4Pwfg/j+B//4D/PgD4+AA=="]},"m15":{"A":[9,11,9,0,3,"HA4FAoNhEIj+QSCwYA=="],"B":[9,11,9,0,3,"fjGYzGYz8YzCYTGfgA=="],"C":[9,11,9,0,3,"HhiIDAYDAYDAIBiHgA=="],"D":[9,11,9,0,3,"fCMQyGQyCQSGQyMfAA=="],"E":[9,11,9,0,3,"fzAYDAYD+YDAYDAfwA=="],"F":[9,11,9,0,3,"PxAIBAIB+IBAIBAIAA=="],"G":[9,11,9,0,3,"HhmYDAQCOQSCYRmHgA=="],"H":[9,11,9,0,3,"QSCQSCQT+QSCQSCQQA=="],"I":[9,11,9,0,3,"fwQCAQCAQCAQCAQfwA=="],"J":[9,11,9,0,3,"HgEAgEAgEAgMBiMPAA=="],"K":[9,11,9,0,3,"QSERCYeDwbCMQiGQYA=="],"L":[9,11,9,0,3,"IBAIBAIBAIBAIBAPwA=="],"M":[9,11,9,0,3,"YzGYyqVS6SSCQSCQQA=="],"N":[9,11,9,0,3,"YTicSiWSSTSKRyGQwA=="],"O":[9,11,9,0,3,"HBEYzGQSCQTGYxEHAA=="],"P":[9,11,9,0,3,"fjGYTCYTGfjAYDAYAA=="],"Q":[9,13,9,0,3,"HBEYzGQSCQTGYxEHgMAg"],"R":[10,11,9,0,3,"fBiGMYxiHwZhiGMYRhg="],"S":[9,11,9,0,3,"HBEYDAYA4AwCATGPgA=="],"T":[9,11,9,0,3,"/4QCAQCAQCAQCAQCAA=="],"U":[9,11,9,0,3,"YzGYzGYzGYzGYxGHAA=="],"V":[9,11,9,0,3,"QSCYzGIhENgoFA4HAA=="],"W":[10,11,9,0,3,"gLBsGSZdF0VR3HcYwiA="],"X":[9,11,9,0,3,"YRGMgoHAYHBsIjGwYA=="],"Y":[9,11,9,0,3,"QTGIhsHA4CAQCAQCAA=="],"Z":[9,11,9,0,3,"fwGAwMDAYGAgMDAf4A=="],"a":[9,8,9,0,6,"HBEAx+YyGZx+"],"b":[9,11,9,0,3,"YDAYD8czGYTCYTkfgA=="],"c":[9,8,9,0,6,"HhiIDAYBAMQ8"],"d":[9,11,9,0,3,"AwGAx+JzGQyGYxOPwA=="],"e":[9,8,9,0,6,"HBEYSCfyAIQ8"],"f":[9,11,9,0,3,"DwQCD+CAQCAQCAQCAA=="],"g":[9,11,9,0,6,"PxOYyGQzGJx+AhEHAA=="],"h":[9,11,9,0,3,"YDAYDccjGYzGYzGYwA=="],"i":[9,11,9,0,3,"CAQABwCAQCAQCAQfwA=="],"j":[9,14,9,0,3,"DAYAB4DAYDAYDAYDAYCDwA=="],"k":[9,11,9,0,3,"IBAIBGJhYOBIJhGIQA=="],"l":[9,11,9,0,3,"eAwGAwGAwGAwGAQDwA=="],"m":[9,8,9,0,6,"fySSSSSSSSSS"],"n":[9,8,9,0,6,"bjkYzGYzGYzG"],"o":[9,8,9,0,6,"HBEYyCQTGIg4"],"p":[9,11,9,0,6,"fjkYzCYTGcj8YDAYAA=="],"q":[9,11,9,0,6,"HxGYyGQzGIx+AwGAwA=="],"r":[9,8,9,0,6,"FwwEAgEAgEAg"],"s":[9,8,9,0,6,"HBEIBwBgEIg4"],"t":[9,10,9,0,4,"GAwfwwGAwGAwGAeA"],"u":[9,8,9,0,6,"YzGYzGYzGIx+"],"v":[9,8,9,0,6,"QTGIhENgoHA4"],"w":[10,8,9,0,6,"gLBkkSRVHcNgiA=="],"x":[9,8,9,0,6,"YxEFAYHBsIiC"],"y":[9,11,9,0,6,"QTGIhkFgoHAQCAwcAA=="],"z":[9,8,9,0,6,"PwEBgYGAgID+"],"0":[9,11,9,0,3,"HBEYzGaSSYTGYxEHAA=="],"1":[9,11,9,0,3,"HBYDAYDAYDAYDAYPwA=="],"2":[9,11,9,0,3,"PDMAwGAgMDAwMBAfwA=="],"3":[9,11,9,0,3,"PCEAwGBg4AgGAyEPAA=="],"4":[9,11,9,0,3,"BgcHgsJhMRj+BgMBgA=="],"5":[9,11,9,0,3,"PhAIBAPAMAwGAyMPAA=="],"6":[9,11,9,0,3,"HhgYDAXjGYzCYxGHgA=="],"7":[9,11,9,0,3,"fwGAgMBAIDAQGAwEAA=="],"8":[9,11,9,0,3,"HBEYzGIg4IzGYzGPgA=="],"9":[9,11,9,0,3,"PDEYyGYzGPQGAwMPAA=="]," ":[9,0,9,0,14,""],".":[9,2,9,0,12,"CAQA"],",":[9,4,9,0,12,"DAQGAgA="],"-":[9,5,9,0,9,"HAAAAAAA"],"/":[9,12,9,0,3,"AwEBgIDAQGAgMBAYCAA="],"(":[9,13,9,0,3,"BAYCAQGAw'''
r'''GAwGAQCAYBA"],")":[9,13,9,0,3,"EAwCAQDAYDAYDAQCAwEA"],"'":[9,11,9,0,3,"CAQCAQAAAAAAAAAAAA=="],"\"":[9,11,9,0,3,"NhsNhsAAAAAAAAAAAA=="],":":[9,8,9,0,6,"CAQAAAAAACAQ"],";":[9,10,9,0,6,"CAQAAAAAADAQGAgA"],"+":[9,8,9,0,6,"CAQCD+CAQCAA"],"=":[9,7,9,0,7,"fwAAD+AAAAA="],"<":[9,8,9,0,6,"AQeODAOAeAQA"],">":[9,8,9,0,6,"QDwDgGDjwQAA"],"•":[9,8,9,0,6,"HB8Pg4AAAAAA"],"—":[10,5,9,0,9,"/4AAAAAAAA=="],"–":[10,5,9,0,9,"/4AAAAAAAA=="],"&":[9,11,9,0,3,"HBAIBgMCRTOPQzGPYA=="],"!":[9,11,9,0,3,"CAQCAQCAQCAAAAQCAA=="],"?":[9,11,9,0,3,"HBEAwEBgYCAQAAQCAA=="],"%":[9,11,9,0,3,"cGQiGQcw4ZwbCITBwA=="],"#":[9,11,9,0,3,"CQ2Ej/EhsJH+JBYSAA=="],"Š":[9,14,9,0,0,"FA4AA4IjAYDAHAGAQCYx8A=="],"Ž":[9,14,9,0,0,"FA4AD+AwGBgYDAwEBgYD/A=="],"Č":[9,14,9,0,0,"EgYAA8MRAYDAYDAYBAMQ8A=="],"Ć":[9,14,9,0,0,"BgYAA8MRAYDAYDAYBAMQ8A=="],"Đ":[9,11,9,0,3,"fCMQyGQ3iQSGQyMfAA=="],"š":[9,12,9,0,2,"NgoCAAHBEIBwBgEIg4A="],"ž":[9,12,9,0,2,"NgoCAAPwEBgYGAgID+A="],"č":[9,12,9,0,2,"EgcDAAHhiIDAYBAMQ8A="],"ć":[9,12,9,0,2,"AgIDAAHhiIDAYBAMQ8A="],"đ":[10,11,9,0,3,"AwPgMPwnGMQxDGMJw/A="]}}}'''
)
GLYPH_DATA = json.loads(_GLYPH_JSON)
ASC = GLYPH_DATA["asc"]
GLYPHS = GLYPH_DATA["glyphs"]


# ------------------------------------------------------------------ colours
PAPER = (247, 242, 228)
PAPER_EDGE = (200, 190, 165)
INK = (28, 39, 51)
GREY = (90, 100, 112)
TEAL = (14, 79, 74)
GOLD = (176, 141, 46)
GOLD_DARK = (150, 110, 20)
BLUE = (43, 79, 158)
PURPLE = (107, 63, 160)
GREEN = (46, 125, 79)
RED = (176, 58, 46)
BROWN = (122, 74, 33)
SKIN = (226, 171, 124)
HAIR = (56, 40, 28)
JACKET = (36, 46, 64)


def star_points(cx, cy, r_out, r_in, n=5):
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = math.pi * i / n - math.pi / 2
        pts.append((int(round(cx + r * math.cos(a))),
                    int(round(cy + r * math.sin(a)))))
    return pts


def draw_portrait(cv, x0, y0, x1, y1):
    """Stylised flat-illustration passport portrait of Elena Marovic."""
    # photo background: soft vertical gradient
    for y in range(y0, y1 + 1):
        t = (y - y0) / float(max(1, y1 - y0))
        c = (int(210 + (186 - 210) * t),
             int(217 + (194 - 217) * t),
             int(224 + (203 - 224) * t))
        cv._hspan(x0, x1, y, c)
    cx = (x0 + x1) // 2
    # shoulders / jacket
    cv.ellipse(cx, y1 + 6, 78, 58, JACKET)
    # shirt V
    cv.poly([(cx - 18, y0 + 124), (cx + 18, y0 + 124), (cx, y0 + 160)],
            (245, 245, 240))
    # neck
    cv.fill_rect(cx - 12, y0 + 96, cx + 12, y0 + 130, SKIN)
    # hair behind the head
    cv.ellipse(cx, y0 + 40, 40, 38, HAIR)
    # head
    cv.ellipse(cx, y0 + 63, 34, 42, SKIN)
    # hair cap with a centre part
    cv.ellipse(cx, y0 + 28, 36, 26, HAIR)
    # side strands
    cv.poly([(cx - 32, y0 + 38), (cx - 20, y0 + 40), (cx - 22, y0 + 120),
             (cx - 34, y0 + 120)], HAIR)
    cv.poly([(cx + 32, y0 + 38), (cx + 20, y0 + 40), (cx + 22, y0 + 120),
             (cx + 34, y0 + 120)], HAIR)
    # eyebrows, eyes, nose, lips, cheeks
    cv.line(cx - 21, y0 + 58, cx - 7, y0 + 56, HAIR, wd=2)
    cv.line(cx + 7, y0 + 56, cx + 21, y0 + 58, HAIR, wd=2)
    cv.ellipse(cx - 14, y0 + 67, 6, 3, (250, 250, 248))
    cv.ellipse(cx + 14, y0 + 67, 6, 3, (250, 250, 248))
    cv.circle(cx - 14, y0 + 67, 2, (30, 30, 30))
    cv.circle(cx + 14, y0 + 67, 2, (30, 30, 30))
    cv.line(cx - 20, y0 + 64, cx - 8, y0 + 64, (30, 30, 30), wd=1)
    cv.line(cx + 8, y0 + 64, cx + 20, y0 + 64, (30, 30, 30), wd=1)
    cv.line(cx, y0 + 70, cx - 2, y0 + 84, (198, 145, 108), wd=1)
    cv.line(cx - 4, y0 + 84, cx + 3, y0 + 84, (198, 145, 108), wd=1)
    cv.ellipse(cx, y0 + 95, 8, 3, (170, 92, 82))
    cv.ellipse(cx - 19, y0 + 81, 7, 5, (238, 186, 155), a=50)
    cv.ellipse(cx + 19, y0 + 81, 7, 5, (238, 186, 155), a=50)


def draw_round_stamp(cv, cx, cy):
    """Circular Drenovar issue stamp, drawn on its own canvas, rotated."""
    s = Canvas(140, 140)
    s.ring(70, 70, 56, TEAL, wd=3)
    s.ring(70, 70, 46, TEAL, wd=1)
    draw_text(s, "KAVERIA", "b16", 70, 56, TEAL, align="center")
    draw_text(s, "DRENOVAR", "b14", 70, 76, TEAL, align="center")
    draw_text(s, "12 JUN 2023", "r12", 70, 94, TEAL, align="center")
    rot = rotate(s, -8)
    cv.blit(rot, cx - rot.w // 2, cy - rot.h // 2)


def draw_map(cv, x0, y0, x1, y1):
    """Little map of Kaveria and its three neighbours."""
    cv.fill_rect(x0, y0, x1, y1, (240, 242, 235))
    cv.rect(x0, y0, x1, y1, GREY, wd=1)
    draw_text(cv, "KAVERIA AND ITS NEIGHBOURS", "b14", x0 + 16, y0 + 24,
              INK)
    # the country
    land = [(610, 880), (585, 800), (625, 725), (700, 700), (790, 715),
            (865, 755), (905, 815), (855, 880), (725, 892), (645, 888)]
    cv.poly(land, (168, 196, 180))
    cv.polyline(land + [land[0]], TEAL, wd=2)
    # river
    cv.polyline([(700, 705), (730, 760), (720, 800), (745, 850),
                 (700, 888)], (70, 120, 160), wd=2)
    # capital
    cv.poly(star_points(745, 795, 9, 4), GOLD_DARK)
    draw_text(cv, "DRENOVAR", "b14", 762, 800, INK)
    # neighbours
    draw_text(cv, "VELMARA", "r12", 545, 760, GREY)
    draw_text(cv, "OSTROVIA", "r12", 900, 712, GREY)
    draw_text(cv, "TARNOVIA", "r12", 905, 868, GREY)
    # compass + scale
    draw_text(cv, "N", "b14", 975, 694, INK, align="center")
    cv.line(975, 700, 975, 724, INK, wd=2)
    cv.poly([(975, 694), (970, 704), (980, 704)], INK)
    draw_text(cv, "0 — 50 km", "r10", 548, 884, GREY)
    cv.line(548, 890, 608, 890, INK, wd=2)
    cv.line(548, 886, 548, 894, INK, wd=1)
    cv.line(608, 886, 608, 894, INK, wd=1)


def draw_data_page(cv):
    # header band
    cv.fill_rect(532, 20, 1004, 92, TEAL)
    draw_text(cv, "REPUBLIC OF KAVERIA", "b30", 768, 60, (255, 255, 255),
              align="center")
    draw_text(cv, "REPUBLIKA KAVERIJA  •  PASSPORT — PUTOVNICA", "r12",
              768, 82, (235, 240, 235), align="center")
    cv.fill_rect(532, 92, 1004, 95, GOLD)
    # portrait
    draw_portrait(cv, 543, 115, 693, 299)
    cv.rect(540, 112, 696, 302, INK, wd=2)
    # gold embossed seal overlapping the photo corner (clear of the fields)
    cv.ring(676, 292, 16, GOLD, wd=3)
    cv.ring(676, 292, 11, GOLD, wd=1)
    cv.poly([(668, 297), (673, 288), (677, 293), (681, 286), (686, 297)],
            GOLD)
    # fields
    fields = [
        ("SURNAME / PREZIME", "MAROVIĆ"),
        ("GIVEN NAMES / IMENA", "ELENA"),
        ("NATIONALITY / DRŽAVLJANSTVO", "KAVERIAN"),
        ("DATE OF BIRTH / DATUM ROĐENJA", "14 MAR 1991"),
        ("PLACE OF BIRTH / MJESTO ROĐENJA", "DRENOVAR"),
        ("SEX / SPOL", "F"),
        ("DATE OF ISSUE / DATUM IZDAVANJA", "12 JUN 2023"),
        ("DATE OF EXPIRY / DATUM ISTEKA", "12 JUN 2033"),
        ("AUTHORITY / TIJELO", "MINISTRY OF INTERIOR — DRENOVAR"),
        ("DOCUMENT No. / BROJ DOKUMENTA", "KV 4829173"),
    ]
    y = 128
    for label, value in fields:
        draw_text(cv, label, "r10", 712, y, GREY)
        draw_text(cv, value, "b14", 712, y + 14, INK)
        y += 27
    # signature
    draw_text(cv, "HOLDER'S SIGNATURE / POTPIS NOSIOCA", "r10", 540, 432,
              GREY)
    cv.polyline([(560, 452), (575, 440), (590, 455), (605, 442),
                 (620, 458), (635, 445), (650, 455), (665, 442),
                 (680, 452), (700, 445), (720, 455), (740, 448),
                 (760, 452)], (30, 40, 55), wd=2)
    cv.line(540, 468, 1004, 468, GREY, wd=1)
    # observations
    cv.rect(540, 492, 1004, 640, GREY, wd=1)
    draw_text(cv, "OBSERVATIONS / NAPOMENE", "b14", 556, 516, INK)
    draw_text(cv, "1.  This passport is valid for travel to all countries.",
              "r12", 556, 542, INK)
    draw_text(cv, "2.  The holder is a citizen of the Republic of Kaveria.",
              "r12", 556, 564, INK)
    draw_text(cv, "3.  If lost, return it to the nearest Kaverian mission.",
              "r12", 556, 586, INK)
    draw_text(cv, "Issued at Drenovar, 12 June 2023.", "r12", 556, 612, INK)
    # map
    draw_map(cv, 540, 660, 1004, 900)
    # machine-readable zone
    cv.fill_rect(532, 916, 1004, 996, (255, 255, 255))
    cv.rect(532, 916, 1004, 996, GREY, wd=1)
    line1, line2 = mrz_lines()
    draw_text(cv, line1, "m15", 768, 948, INK, align="center")
    draw_text(cv, line2, "m15", 768, 974, INK, align="center")


def draw_visa_page(cv):
    draw_text(cv, "VISAS", "b16", 24, 46, INK)
    draw_text(cv, "VIZE", "r12", 100, 46, GREY)
    draw_text(cv, "12", "b16", 488, 46, INK, align="right")
    cv.line(20, 56, 492, 56, INK, wd=1)
    draw_text(cv, "REPUBLIC OF KAVERIA — VISA PAGES", "r10", 24, 74, GREY)
    # faint mountain watermark
    cv.polyline([(30, 700), (90, 640), (150, 700), (210, 650), (270, 700),
                 (330, 645), (390, 700), (450, 660), (492, 700)],
                (228, 222, 200), wd=2)
    cv.polyline([(30, 740), (90, 685), (150, 740), (210, 690), (270, 740),
                 (330, 685), (390, 740), (450, 700), (492, 740)],
                (228, 222, 200), wd=2)
    # entry / exit stamps from the three neighbours, in travel order
    stamps = [
        ("VELMARA", "02 SEP 2023", "09 SEP 2023", BLUE, -3, 175),
        ("OSTROVIA", "21 JAN 2024", "28 JAN 2024", PURPLE, 2.5, 305),
        ("TARNOVIA", "14 MAY 2024", "02 JUN 2024", GREEN, -2, 435),
    ]
    for country, entry, exit_, ink, angle, cy in stamps:
        st = make_stamp([
            (country, "b16", ink),
            ("ENTRY  •  " + entry, "r12", ink),
            ("EXIT  •  " + exit_, "r12", ink),
        ], ink, 380, 96)
        rot = rotate(st, angle)
        cv.blit(rot, 256 - rot.w // 2, cy - rot.h // 2)
    # round Drenovar issue stamp
    draw_round_stamp(cv, 120, 600)
    # the telling paperwork: visa condition + consular fee
    cond = make_stamp([
        ("EMPLOYMENT PROHIBITED", "b14", RED),
        ("TOURIST STAY — 90 DAYS", "r12", RED),
    ], RED, 380, 72)
    rot = rotate(cond, -6)
    cv.blit(rot, 256 - rot.w // 2, 715 - rot.h // 2)
    fee = make_stamp([
        ("CONSULAR FEE PAID", "b14", BROWN),
        ("40 KAV  •  DRENOVAR", "r12", BROWN),
    ], BROWN, 300, 64, double=False)
    rot = rotate(fee, 4)
    cv.blit(rot, 256 - rot.w // 2, 815 - rot.h // 2)
    # small print
    draw_text(cv, "This passport remains the property of the Republic "
              "of Kaveria.", "r10", 256, 950, GREY, align="center")
    draw_text(cv, "If found, please return it to the Ministry of "
              "Interior, Drenovar.", "r10", 256, 966, GREY, align="center")


def draw_spread():
    cv = Canvas(W, H, PAPER)
    # page edges and gutter
    cv.fill_rect(508, 4, 516, 1020, (210, 202, 178))
    cv.rect(4, 4, 508, 1020, PAPER_EDGE, wd=1)
    cv.rect(516, 4, 1020, 1020, PAPER_EDGE, wd=1)
    draw_visa_page(cv)
    draw_data_page(cv)
    return cv


def main():
    cv = draw_spread()
    data = png_bytes(cv)
    os.makedirs("/output", exist_ok=True)
    with open("/output/entry.png", "wb") as f:
        f.write(data)
    print("wrote /output/entry.png: %d bytes, %dx%d"
          % (len(data), cv.w, cv.h))


if __name__ == "__main__":
    main()
