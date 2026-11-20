#!/usr/bin/env bash
set -uo pipefail
yt-dlp -o source.mp4 "$CLIP_URL"
python3 make_subs.py source.mp4 || echo "subs skipped"
FILTER="crop=ih*9/16:ih,scale=1080:1920"
if [ -f subs.ass ]; then FILTER="$FILTER,ass=subs.ass"; fi
ffmpeg -y -i source.mp4 -vf "$FILTER" -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k out.mp4
ls -la out.mp4
