import base64, json, os, sys, urllib.request

MODELS = ["ag/gemini-3.8-flash", "gemini/gemini-3.6-flash", "gemini/gemini-3.5-flash-lite"]
URL = "http://100.85.59.117:20128/v1/chat/completions"
KEY = os.environ["NINEROUTER_API_KEY"]

def transcribe(path, prompt):
    b64 = base64.b64encode(open(path, 'rb').read()).decode()
    for m in MODELS:
        payload = {"model": m, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}}]}], "max_tokens": 3000}
        req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
        try:
            r = urllib.request.urlopen(req, timeout=300)
        except Exception as e:
            print(f"[{m}] {e}", file=sys.stderr)
            continue
        out = []
        for line in r:
            line = line.decode().strip()
            if not line.startswith('data: '):
                continue
            d = line[6:]
            if d == '[DONE]':
                break
            try:
                j = json.loads(d)
                c = j['choices'][0].get('delta', {}).get('content')
                if c:
                    out.append(c)
            except Exception:
                pass
        txt = ''.join(out).strip()
        if txt:
            return txt
    return ""

if __name__ == "__main__":
    p = ("Transcribe this audio verbatim with speaker labels. "
         "Output only the transcript, no commentary.")
    print(transcribe(sys.argv[1], p))
