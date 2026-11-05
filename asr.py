import base64, json, os, urllib.request, sys
b64 = base64.b64encode(open(sys.argv[1],'rb').read()).decode()
payload = {"model":"gemini/gemini-3.6-flash","messages":[{"role":"user","content":[
   {"type":"text","text":"Transcribe this audio verbatim with speaker labels (Speaker 1 / Speaker 2). Output only the transcript, no commentary."},
   {"type":"input_audio","input_audio":{"data":b64,"format":"mp3"}}]}],"max_tokens":3000}
req = urllib.request.Request("http://100.85.59.117:20128/v1/chat/completions",
  data=json.dumps(payload).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["NINEROUTER_API_KEY"]})
r = urllib.request.urlopen(req, timeout=300)
out=[]
for line in r:
    line=line.decode().strip()
    if not line.startswith('data: '): continue
    d=line[6:]
    if d=='[DONE]': break
    try:
        j=json.loads(d)
        c=j['choices'][0].get('delta',{}).get('content')
        if c: out.append(c)
    except Exception: pass
print(''.join(out))
