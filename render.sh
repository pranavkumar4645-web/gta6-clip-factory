#!/usr/bin/env bash
set -uo pipefail
yt-dlp -o source.mp4 "$CLIP_URL"
python3 make_subs.py source.mp4 || echo "subs skipped"
printf '%s' "$TITLE" | fold -s -w 26 | head -2 > hook.txt
SUB=""
if [ -f subs.ass ]; then SUB=",ass=subs.ass"; fi
VF="[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=brightness=-0.15[bg];[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v1];[v1]drawtext=fontfile=/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf:textfile=hook.txt:fontcolor=white:fontsize=62:borderw=6:bordercolor=black:x=(w-text_w)/2:y=150:line_spacing=14${SUB}[vout]"
ffmpeg -y -i source.mp4 -filter_complex "$VF" -map "[vout]" -map 0:a? -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k out.mp4
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 out.mp4)
ffmpeg -y -ss $(awk "BEGIN{print $DUR/2}") -i out.mp4 -frames:v 1 -q:v 2 frame.jpg || echo "thumb skipped"
ls -la out.mp4
