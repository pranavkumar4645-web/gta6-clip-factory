#!/usr/bin/env python3
"""Visual frame gate: skin-pixel analysis to catch adult/NSFW visual content.
Extracts 1 frame per second (160px wide) and computes the fraction of
skin-cluster pixels per frame under several detection rules (the raw clip's
club/night lighting defeats naive daylight RGB, so multiple rules are used).
Default rule: YH (YCbCr skin cluster OR HSV skin hue) -- chosen empirically so
known strip-club footage is rejected and clean gameplay passes.
Rejects if any frame exceeds the single-frame threshold, the average exceeds
the avg threshold, or 3+ consecutive frames exceed the consecutive threshold.
Exits 0 on pass, 7 on rejection. Thresholds/rule can be overridden via env:
VISION_SINGLE, VISION_AVG, VISION_CONSEC, VISION_RULE.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from PIL import Image

SINGLE = float(os.environ.get('VISION_SINGLE', '0.30'))
AVG = float(os.environ.get('VISION_AVG', '0.15'))
CONSEC = float(os.environ.get('VISION_CONSEC', '0.20'))
CONSEC_N = 3
RULE = os.environ.get('VISION_RULE', 'YH')


def rule_fractions(img):
    im = img.convert('RGB')
    d = y = h = n = yh = 0
    tot = 0
    for r, g, b in im.getdata():
        tot += 1
        mx = max(r, g, b)
        mn = min(r, g, b)
        # D: classic uniform daylight RGB skin rule
        if (r > 95 and g > 40 and b > 20 and mx - mn > 15
                and abs(r - g) > 15 and r > g and r > b):
            d += 1
        # Y: YCbCr (BT.601) skin cluster
        cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
        cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
        yb = (77 <= cb <= 127) and (133 <= cr <= 173)
        if yb:
            y += 1
        # H: HSV skin hue range (incl. deep red/pink wrap-around)
        v = mx / 255.0
        s = 0.0 if mx == 0 else (mx - mn) / float(mx)
        hsv = False
        if v > 0.15 and 0.1 <= s <= 0.75:
            if mx != mn:
                if mx == r:
                    hue = 60.0 * (((g - b) / float(mx - mn)) % 6)
                elif mx == g:
                    hue = 60.0 * ((b - r) / float(mx - mn) + 2)
                else:
                    hue = 60.0 * ((r - g) / float(mx - mn) + 4)
            else:
                hue = 0.0
            if hue <= 50 or hue >= 340:
                hsv = True
        if hsv:
            h += 1
        # N: normalized chromaticity (illumination-independent rg)
        s3 = r + g + b
        if s3 > 0:
            rr = r / float(s3)
            gg = g / float(s3)
            if 0.33 <= rr <= 0.55 and 0.22 <= gg <= 0.38 and r > g and r > b:
                n += 1
        if yb or hsv:
            yh += 1
    t = float(tot) if tot else 1.0
    return {'D': d / t, 'Y': y / t, 'H': h / t, 'N': n / t, 'YH': yh / t}


def frame_features(img):
    """Spatial features per frame: darkness, largest connected skin blob,
    central-region skin, blob vertical position (0=top,1=bottom)."""
    im = img.convert('RGB')
    w, h = im.size
    px = list(im.getdata())
    tot = w * h
    skin = [False] * tot
    dark = 0
    for p in range(tot):
        r, g, b = px[p]
        mx = max(r, g, b); mn = min(r, g, b)
        if mx / 255.0 < 0.25:
            dark += 1
        cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
        cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
        yb = (77 <= cb <= 127) and (133 <= cr <= 173)
        v = mx / 255.0
        s = 0.0 if mx == 0 else (mx - mn) / float(mx)
        hsv = False
        if v > 0.15 and 0.1 <= s <= 0.75:
            if mx != mn:
                if mx == r:
                    hue = 60.0 * (((g - b) / float(mx - mn)) % 6)
                elif mx == g:
                    hue = 60.0 * ((b - r) / float(mx - mn) + 2)
                else:
                    hue = 60.0 * ((r - g) / float(mx - mn) + 4)
            else:
                hue = 0.0
            if hue <= 50 or hue >= 340:
                hsv = True
        skin[p] = yb or hsv
    # largest 8-connected component
    seen = [False] * tot
    best = 0
    best_rows = None
    stack = []
    for p0 in range(tot):
        if skin[p0] and not seen[p0]:
            stack = [p0]
            seen[p0] = True
            size = 0
            rmin = w + h; rmax = -1
            while stack:
                c = stack.pop()
                size += 1
                cx = c % w
                cy = c // w
                if cy < rmin: rmin = cy
                if cy > rmax: rmax = cy
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx = cx + dx; ny = cy + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        np_ = ny * w + nx
                        if skin[np_] and not seen[np_]:
                            seen[np_] = True
                            stack.append(np_)
            if size > best:
                best = size
                best_rows = (rmin, rmax)
    csk = 0; ctot = 0
    for y in range(int(h * 0.25), int(h * 0.75)):
        for x in range(int(w * 0.25), int(w * 0.75)):
            ctot += 1
            if skin[y * w + x]:
                csk += 1
    cy_mid = ((best_rows[0] + best_rows[1]) / 2.0 / h) if best_rows else 0.5
    return {'dark': dark / float(tot), 'skin': sum(skin) / float(tot),
            'blob': best / float(tot), 'central': csk / float(max(1, ctot)),
            'blob_y': cy_mid}


def extract_frames(video, outdir):
    subprocess.run(
        ['ffmpeg', '-y', '-i', video, '-vf', 'fps=1,scale=160:-2',
         os.path.join(outdir, 'f%04d.jpg')],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return sorted(glob.glob(os.path.join(outdir, 'f*.jpg')))


def reject_reason(fr):
    if not fr:
        return 'no frames extracted'
    mx = max(fr)
    if mx > SINGLE:
        return 'single frame skin %.1f%% > %.1f%%' % (mx * 100, SINGLE * 100)
    avg = sum(fr) / len(fr)
    if avg > AVG:
        return 'average skin %.1f%% > %.1f%%' % (avg * 100, AVG * 100)
    run = 0
    for x in fr:
        run = run + 1 if x > CONSEC else 0
        if run >= CONSEC_N:
            return '%d consecutive frames over %.1f%% skin' % (run, CONSEC * 100)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('--dump-stats', dest='dump_stats', default=None)
    ap.add_argument('--rule', default=RULE,
                    help='D (daylight RGB), Y (YCbCr), H (HSV), N (chromaticity), YH (Y or H)')
    args = ap.parse_args()
    d = tempfile.mkdtemp(prefix='vframes_')
    try:
        frames = extract_frames(args.video, d)
        fr = []
        all_rules = {k: [] for k in ('D', 'Y', 'H', 'N', 'YH')}
        feats = []
        for f in frames:
            frx = rule_fractions(Image.open(f))
            fr.append(frx[args.rule])
            for k, v in frx.items():
                all_rules[k].append(v)
            print('frame %s: skin %.1f%%' % (os.path.basename(f), frx[args.rule] * 100))
            feats.append(frame_features(Image.open(f)))
        if args.dump_stats:
            with open(args.dump_stats, 'w') as fh:
                json.dump({'video': args.video, 'frames': len(fr), 'rule': args.rule,
                           'rules': all_rules,
                           'fractions': fr,
                           'max': max(fr) if fr else 0.0,
                           'avg': (sum(fr) / len(fr)) if fr else 0.0,
                           'feat': feats}, fh)
        reason = reject_reason(fr)
        if reason:
            mx = max(fr) if fr else 0.0
            print('VISUAL GATE REJECTED (skin %.1f%%): %s' % (mx * 100, reason))
            sys.exit(7)
        print('VISUAL GATE PASSED (max skin %.1f%%, avg %.1f%%)'
              % (max(fr) * 100, sum(fr) / len(fr) * 100))
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    main()
