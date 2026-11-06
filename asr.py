import base64, json, os, urllib.request, sys
import config

b64 = base64.b64encode(open(sys.argv[1], 'rb').read()).decode()
model = config.LLM_MODELS[0] if config.LLM_MODELS else "gpt-4o-mini"
payload = {
    "model": model,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Transcribe this audio verbatim with speaker labels (Speaker 1 / Speaker 2). Output only the transcript, no commentary.",
                },
                {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}},
            ],
        }
    ],
    "max_tokens": 3000,
}
headers = {"Content-Type": "application/json"}
if config.LLM_KEY:
    headers["Authorization"] = f"Bearer {config.LLM_KEY}"

req = urllib.request.Request(config.LLM_URL, data=json.dumps(payload).encode(), headers=headers)
r = urllib.request.urlopen(req, timeout=300)
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
print(''.join(out))
