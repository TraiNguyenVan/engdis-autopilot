import base64, json, os, sys, urllib.request
import config

MODELS = config.LLM_MODELS
URL = config.LLM_URL
KEY = config.LLM_KEY

def transcribe(path, prompt):
    b64 = base64.b64encode(open(path, 'rb').read()).decode()
    for m in MODELS:
        payload = {"model": m, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}}]}], "max_tokens": 3000}
        headers = {"Content-Type": "application/json"}
        if KEY:
            headers["Authorization"] = "Bearer " + KEY
        req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=60)
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
