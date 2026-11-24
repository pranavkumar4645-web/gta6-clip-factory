#!/usr/bin/env python3
"""Visual frame gate: skin-pixel analysis to catch adult/NSFW visual content.
Extracts 1 frame per second (160px wide) and computes the fraction of skin-cluster
pixels per frame. Rejects if any frame is above the single-frame threshold, the
average is above the avg threshold, or 3+ consecutive frames are above the
consecutive threshold. Exits 0 on pass, 7 on rejection.
Thresholds can be overridden via env: VISION_SINGLE, VISION_AVG, VISION_CONSEC.
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


def skin_fraction(img):
    im = img.convert('RGB')
    total = 0
    skin = 0
    for r, g, b in im.getdata():
        total += 1
        if (r > 95 and g > 40 and b > 20
                and max(r, g, b) - min(r, g, b) > 15
                and abs(r - g) > 15 and r > g and r > b):
            skin += 1
    return (skin / total) if total else 0.0


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
    args = ap.parse_args()
    d = tempfile.mkdtemp(prefix='vframes_')
    try:
        frames = extract_frames(args.video, d)
        fr = []
        for f in frames:
            s = skin_fraction(Image.open(f))
            fr.append(s)
            print('frame %s: skin %.1f%%' % (os.path.basename(f), s * 100))
        if args.dump_stats:
            with open(args.dump_stats, 'w') as fh:
                json.dump({'video': args.video, 'frames': len(fr),
                           'fractions': fr,
                           'max': max(fr) if fr else 0.0,
                           'avg': (sum(fr) / len(fr)) if fr else 0.0}, fh)
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
