from faster_whisper import WhisperModel
import sys
model = WhisperModel("base", device="cpu", compute_type="int8")
segments, info = model.transcribe(sys.argv[1], word_timestamps=True)
def ts(sec):
    h = int(sec//3600); m = int(sec%3600//60); s = int(sec%60); cs = int((sec-int(sec))*100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Def,Liberation Sans,54,&H00FFFFFF,&H00000000,&H80000000,-1,4,2,2,70,70,260,1
[Events]
Format: Layer, Start, End, Style, Text
"""
NL = chr(10)
lines = [header]
for seg in segments:
    words = seg.words or []
    chunk = []
    start = None
    for w in words:
        if not chunk:
            start = w.start
        chunk.append(w.word.strip())
        if len(chunk) >= 3 or (w.word.strip().endswith(('.', '!', '?'))):
            lines.append("Dialogue: 0," + ts(start) + "," + ts(w.end) + ",Def," + " ".join(chunk).replace(",", " ").replace(NL, " "))
            chunk = []
    if chunk:
        lines.append("Dialogue: 0," + ts(start) + "," + ts(seg.end) + ",Def," + " ".join(chunk).replace(",", " ").replace(NL, " "))
open("subs.ass", "w").write(NL.join(lines))
print("subs written")
