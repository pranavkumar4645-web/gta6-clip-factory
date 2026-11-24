from faster_whisper import WhisperModel
import sys, os
model = WhisperModel("base", device="cpu", compute_type="int8")
segments, info = model.transcribe(sys.argv[1], word_timestamps=True)
def ts(sec):
    h = int(sec//3600); m = int(sec%3600//60); s = int(sec%60); cs = int((sec-int(sec))*100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Def,Liberation Sans Bold,56,&H00FFFFFF,&H00000000,&HA0000000,-1,5,3,2,60,60,300,1
[Events]
Format: Layer, Start, End, Style, Text
"""
NL = chr(10)
lines = [header]
transcript_words = 0
for seg in segments:
    words = seg.words or []
    if not words:
        continue
    chunk = []
    start = None
    for w in words:
        if not chunk:
            start = w.start
        chunk.append((w.word.strip(), w.start, w.end))
        transcript_words += 1 if w.word.strip() else 0
        if len(chunk) >= 3 or w.word.strip().endswith(('.', '!', '?')):
            key = max(chunk, key=lambda c: len(c[0]))[0]
            text = " ".join(("{\c&H0000FFFF&}" + c[0] + "{\c&H00FFFFFF&}") if c[0] == key and len(key) > 3 else c[0] for c in chunk)
            text = text.replace(",", " ").replace(NL, " ")
            lines.append(f"Dialogue: 0,{ts(start)},{ts(chunk[-1][2])},Def,{text}")
            chunk = []
    if chunk:
        key = max(chunk, key=lambda c: len(c[0]))[0]
        text = " ".join(("{\c&H0000FFFF&}" + c[0] + "{\c&H00FFFFFF&}") if c[0] == key and len(key) > 3 else c[0] for c in chunk)
        text = text.replace(",", " ").replace(NL, " ")
        lines.append(f"Dialogue: 0,{ts(start)},{ts(chunk[-1][2])},Def,{text}")
open("subs.ass", "w").write(NL.join(lines))
open("transcript.txt", "w").write(str(transcript_words))
print("subs written, words:", transcript_words)
