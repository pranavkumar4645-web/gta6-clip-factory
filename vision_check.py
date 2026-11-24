#!/usr/bin/env python3
"""Visual frame gate: catches adult/NSFW visual content (e.g. GTA 6 strip club
scenes with clean titles and no spoken keywords).

How it works: 1 frame per second is extracted (160px wide) and every pixel is
classified as skin using two illumination-tolerant rules (YCbCr skin cluster OR
HSV skin-hue cluster; the naive daylight RGB rule misses dim club lighting).
Per frame we then measure: scene darkness (fraction of pixels with V < 0.25)
and the largest connected skin-colored region (blob). A frame "trips" when the
scene is dark and contains a body-sized skin blob (between BLOB_LO and BLOB_HI
of the frame) -- the signature of a dancer/exposed body in club lighting.
Warm scenery (sunsets, fire) produces very LARGE blobs and is not body-sized;
faces/limbs in normal gameplay produce small or non-persistent blobs.

REJECT if tripping frames make up more than TRIP_RATIO of the clip, or if
TRIP_RUN+ consecutive frames trip. Exits 0 on pass, 7 on rejection.
Tunables via env: VISION_DARK, VISION_BLOB_LO, VISION_BLOB_HI,
VISION_TRIP_RATIO, VISION_TRIP_RUN.
Calibrated against the known-bad Mandy strip-club clip (rejects) and the known-
good Clix clip (passes).
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

DARK = float(os.environ.get('VISION_DARK', '0.65'))
BLOB_LO = float(os.environ.get('VISION_BLOB_LO', '0.04'))
BLOB_HI = float(os.environ.get('VISION_BLOB_HI', '0.32'))
TRIP_RATIO = float(os.environ.get('VISION_TRIP_RATIO', '0.80'))
TRIP_RUN = int(os.environ.get('VISION_TRIP_RUN', '10'))


def skin_dark_blob(img):
    """Return (skin_fraction, dark_fraction, largest_blob_fraction) for a frame."""
    im = img.convert('RGB')
    w, h = im.size
    px = list(im.getdata())
    tot = w * h
    skin = [False] * tot
    skin_n = 0
    dark_n = 0
    for p in range(tot):
        r, g, b = px[p]
        mx = max(r, g, b)
        mn = min(r, g, b)
        if mx / 255.0 < 0.25:
            dark_n += 1
        # YCbCr (BT.601) skin cluster
        cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
        cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
        yb = (77 <= cb <= 127) and (133 <= cr <= 173)
        # HSV skin hue range (incl. deep red/pink wrap-around)
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
        if yb or hsv:
            skin[p] = True
            skin_n += 1
    # largest 8-connected skin component (iterative flood fill)
    seen = [False] * tot
    best = 0
    stack = []
    for p0 in range(tot):
        if skin[p0] and not seen[p0]:
            stack = [p0]
            seen[p0] = True
            size = 0
            while stack:
                c = stack.pop()
                size += 1
                cx = c % w
                cy = c // w
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx = cx + dx
                    ny = cy + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        np_ = ny * w + nx
                        if skin[np_] and not seen[np_]:
                            seen[np_] = True
                            stack.append(np_)
            if size > best:
                best = size
    return (skin_n / float(tot), dark_n / float(tot), best / float(tot))


def extract_frames(video, outdir):
    subprocess.run(
        ['ffmpeg', '-y', '-i', video, '-vf', 'fps=1,scale=160:-2',
         os.path.join(outdir, 'f%04d.jpg')],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return sorted(glob.glob(os.path.join(outdir, 'f*.jpg')))


def reject_reason(feats):
    if not feats:
        return 'no frames extracted'
    trips = [f['dark'] > DARK and BLOB_LO < f['blob'] < BLOB_HI for f in feats]
    n = len(trips)
    ratio = sum(trips) / float(n)
    if ratio > TRIP_RATIO:
        return '%d/%d frames show a dark scene with a body-sized skin blob' % (sum(trips), n)
    run = mx = 0
    for t in trips:
        run = run + 1 if t else 0
        mx = max(mx, run)
    if mx > TRIP_RUN:
        return '%d consecutive frames with a body-sized skin blob in a dark scene' % mx
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('--dump-stats', dest='dump_stats', default=None)
    args = ap.parse_args()
    d = tempfile.mkdtemp(prefix='vframes_')
    try:
        frames = extract_frames(args.video, d)
        feats = []
        for f in frames:
            s, dk, bl = skin_dark_blob(Image.open(f))
            trip = dk > DARK and BLOB_LO < bl < BLOB_HI
            feats.append({'skin': s, 'dark': dk, 'blob': bl, 'trip': trip})
            print('frame %s: skin %.1f%% dark %.1f%% blob %.1f%% %s'
                  % (os.path.basename(f), s * 100, dk * 100, bl * 100,
                     'TRIP' if trip else ''))
        if args.dump_stats:
            with open(args.dump_stats, 'w') as fh:
                json.dump({'video': args.video, 'frames': len(feats), 'feat': feats}, fh)
        reason = reject_reason(feats)
        if reason:
            mx = max(f['skin'] for f in feats) if feats else 0.0
            print('VISUAL GATE REJECTED (skin %.1f%%): %s' % (mx * 100, reason))
            sys.exit(7)
        ratio = sum(1 for f in feats if f['trip']) / float(max(1, len(feats)))
        print('VISUAL GATE PASSED (max skin %.1f%%, body-blob frames %.0f%%)'
              % (max(f['skin'] for f in feats) * 100, ratio * 100))
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    main()
