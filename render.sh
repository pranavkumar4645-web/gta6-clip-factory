#!/usr/bin/env bash
set -uo pipefail
yt-dlp -o source.mp4 "$CLIP_URL"
python3 make_subs.py source.mp4 || echo "subs skipped"
# content safety screen: reject on explicit content in TITLE or actual spoken transcript
BADWORDS='nude|naked|nsfw|porn|sex|sexy|sexual|18\+|xxx|erotic|orgy|threesom|blowjob|handjob|boob|tits?|titties|ass|butt|ass cheeks|onlyfans|horny|strip|stripper|pole danc|lap danc|lapdance|pole|mandy|lulu|brothel|prostitut|escort|kinky|fetish|bdsm|lingerie|panties|thong|topless|topless|shower scene|uncensor|hot scene|leaked scene|scene leak|gore|behead|decapitat|mutilat|disembowel|suicide|kill myself|self harm|school shooting|shooting up|terrorist|bomb making|slur|n-word|fag|retard|nsfl|pornhub|orgasm|dick|cock|nipples|nipple|asshole|fucked|fucking|fuck|shit|bitch|corpse|strip club|pole dance|lap dance|brothel|private dance|gyatt|gyat|thicc|baddie|bbl|backshots|twerk|twerking|milf|dilf|zaddy|cougar|cakez|big cake'
UNSAFE=0
if printf "%s" "$TITLE" | grep -qiE "$BADWORDS"; then UNSAFE=1; fi
if [ -f subs.ass ] && grep -qiE "$BADWORDS" subs.ass; then UNSAFE=1; fi
if [ "$UNSAFE" -eq 1 ]; then
  echo "REJECTED: clip failed content safety screen, not rendering or releasing"
  rm -f source.mp4 subs.ass transcript.txt
  exit 3
fi
# caption completeness check: if speech was detected but no captions, reject
if [ -f transcript.txt ] && [ "$(cat transcript.txt)" != "0" ] && [ ! -s subs.ass ]; then
  echo "REJECTED: speech detected but captions missing"
  exit 4
fi
# fonts: modern display font for the title
curl -sL -o Anton.ttf "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf" || true
TITLEFONT="Anton.ttf"
[ -s "$TITLEFONT" ] || TITLEFONT="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
# wrap hook title to max 2 lines, auto-size by length
printf '%s' "$TITLE" | fold -s -w 22 | head -2 > hook.txt
LEN=$(printf "%s" "$TITLE" | wc -c)
FS=66; [ "$LEN" -gt 45 ] && FS=54; [ "$LEN" -gt 80 ] && FS=46
SUB=""
if [ -s subs.ass ]; then SUB=",ass=subs.ass"; fi
VF="[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,eq=brightness=-0.15[bg];[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v1];[v1]drawtext=fontfile=$TITLEFONT:textfile=hook.txt:fontcolor=white:fontsize=${FS}:borderw=5:bordercolor=black:shadowx=3:shadowy=3:shadowcolor=black@0.6:x=(w-text_w)/2:y=150:line_spacing=14${SUB}[vout]"
ffmpeg -y -i source.mp4 -filter_complex "$VF" -map "[vout]" -map 0:a? -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k out.mp4
# final QC gate: render must exist, be non-trivial, and playable
if [ ! -s out.mp4 ]; then echo "REJECTED: render failed"; exit 5; fi
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 out.mp4 || echo 0)
SIZE=$(stat -c%s out.mp4 || echo 0)
if [ "${DUR%.*}" -lt 3 ] || [ "$SIZE" -lt 200000 ]; then echo "REJECTED: render too short or tiny"; exit 6; fi
ffmpeg -y -ss $(awk "BEGIN{print int($DUR/2)}") -i out.mp4 -frames:v 1 -q:v 2 frame.jpg || echo "thumb skipped"
ls -la out.mp4 frame.jpg
