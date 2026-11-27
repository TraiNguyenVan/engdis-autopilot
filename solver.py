"""Automated solver for English Discoveries (ed22.engdis.com) lessons.

Drives own headless Chromium over CDP; answers via a cheap remote LLM.
Prints one terse line per task.
"""
import base64, hashlib, http.client, json, os, socket, subprocess, sys, tempfile, threading, time, urllib.request

import edlib
import config

_monotonic = time.monotonic
_ORIG_URLOPEN = urllib.request.urlopen


class _ConfigTimeout(int):
    pass


LLM_URL = config.LLM_URL
LLM_KEY = config.LLM_KEY
LLM_MODELS = list(config.LLM_MODELS)
LLM_TIMEOUT = _ConfigTimeout(config.LLM_TIMEOUT)

SCRATCH = config.SCRATCH


# ---------- LLM ----------
def _shutdown_sock(sock):
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


def _extract_sock(obj):
    for candidate in (obj, getattr(obj, "fp", None)):
        if candidate is None:
            continue
        fp = getattr(candidate, "fp", None)
        for stream in (candidate, fp, getattr(fp, "raw", None), getattr(candidate, "raw", None)):
            sock = getattr(stream, "_sock", None)
            if sock is not None:
                return sock
    return None


def _abort_response(resp):
    if resp is None:
        return
    _shutdown_sock(_extract_sock(resp))
    if hasattr(resp, "close"):
        try:
            resp.close()
        except Exception:
            pass


def _register_sock(state, lock, sock):
    if sock is None:
        return
    abort_now = False
    with lock:
        if state["aborted"]:
            abort_now = True
        elif sock not in state["socks"]:
            state["socks"].append(sock)
    if abort_now:
        _shutdown_sock(sock)
        raise TimeoutError("LLM request aborted after timeout")


def _open_cancellable(req, timeout, deadline, state, lock):
    if urllib.request.urlopen is not _ORIG_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout)

    def _create_conn(address, conn_timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        host, port = address
        last_err = None
        # System DNS cannot be interrupted by closing the request socket.
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        if not infos:
            raise OSError("getaddrinfo returns an empty list")
        for af, socktype, proto, _canon, sa in infos:
            sock = None
            try:
                remaining = deadline - _monotonic()
                if remaining <= 0:
                    raise TimeoutError("LLM request exceeded %ss total timeout" % timeout)
                sock = socket.socket(af, socktype, proto)
                _register_sock(state, lock, sock)
                if conn_timeout is socket._GLOBAL_DEFAULT_TIMEOUT or conn_timeout is None:
                    eff_timeout = remaining
                else:
                    eff_timeout = min(conn_timeout, remaining)
                sock.settimeout(eff_timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sa)
                return sock
            except Exception as exc:
                last_err = exc
                if sock is not None:
                    _shutdown_sock(sock)
                if state["aborted"] or _monotonic() >= deadline:
                    break
        if last_err is not None:
            raise last_err
        raise TimeoutError("LLM request exceeded %ss total timeout" % timeout)

    class _HTTPConn(http.client.HTTPConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = _create_conn

        def connect(self):
            super().connect()
            _register_sock(state, lock, self.sock)

    class _HTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, r):
            return self.do_open(_HTTPConn, r)

    handlers = [_HTTPHandler]
    if hasattr(urllib.request, "HTTPSHandler") and hasattr(http.client, "HTTPSConnection"):
        class _HTTPSConn(http.client.HTTPSConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._create_connection = _create_conn

            def connect(self):
                super().connect()
                _register_sock(state, lock, self.sock)

        class _HTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, r):
                return self.do_open(_HTTPSConn, r, context=self._context)

        handlers.append(_HTTPSHandler)

    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)


def _read_with_deadline(resp, deadline, timeout, sink=None, allow_partial=False):
    reader = resp.read1 if hasattr(resp, "read1") else getattr(getattr(resp, "fp", None), "read1", None)
    if reader is None:
        data = resp.read()
        if sink is not None and data:
            sink.append(data)
        if _monotonic() > deadline and not allow_partial:
            raise TimeoutError("LLM request exceeded %ss total timeout" % timeout)
        return data
    sock = _extract_sock(resp)
    chunks = sink if sink is not None else []
    while True:
        remaining = deadline - _monotonic()
        if remaining <= 0:
            if allow_partial:
                break
            raise TimeoutError("LLM request exceeded %ss total timeout" % timeout)
        if sock is not None and hasattr(sock, "settimeout"):
            try:
                sock.settimeout(remaining)
            except Exception:
                pass
        chunk = reader(16384)
        if not chunk:
            # HTTPResponse.read1() closes on early EOF without raising, unlike
            # read(); a positive remaining length means the body is truncated.
            if not allow_partial and getattr(resp, "length", None):
                raise http.client.IncompleteRead(b"".join(chunks), resp.length)
            break
        chunks.append(chunk)
    if _monotonic() > deadline and not allow_partial:
        raise TimeoutError("LLM request exceeded %ss total timeout" % timeout)
    return b"".join(chunks)


def _fetch_with_deadline(req, timeout):
    deadline = _monotonic() + timeout
    lock = threading.Lock()
    state = {
        "resp": None,
        "socks": [],
        "body": None,
        "http_err": None,
        "err_chunks": [],
        "exc": None,
        "aborted": False,
    }

    def _worker():
        resp = None
        try:
            resp = _open_cancellable(req, timeout, deadline, state, lock)
            state["resp"] = resp
            if state["aborted"] or _monotonic() > deadline:
                state["aborted"] = True
                return
            state["body"] = _read_with_deadline(resp, deadline, timeout).decode()
        except urllib.error.HTTPError as e:
            state["http_err"] = e
            state["resp"] = e
            if not state["aborted"]:
                try:
                    _read_with_deadline(e, deadline, timeout, sink=state["err_chunks"], allow_partial=True)
                except Exception:
                    pass
        except Exception as e:
            state["exc"] = e
        finally:
            with lock:
                aborted = state["aborted"]
                tracked_socks = list(state["socks"])
            if aborted:
                for s in tracked_socks:
                    _shutdown_sock(s)
                _abort_response(state["resp"] or resp)
            else:
                if state["http_err"] is not None and hasattr(state["http_err"], "close"):
                    try:
                        state["http_err"].close()
                    except Exception:
                        pass
                elif resp is not None and hasattr(resp, "close"):
                    try:
                        resp.close()
                    except Exception:
                        pass
                for s in tracked_socks:
                    try:
                        s.close()
                    except Exception:
                        pass

    worker = threading.Thread(target=_worker, name="ed-llm-fetch", daemon=True)
    worker.start()
    remaining = deadline - _monotonic()
    if remaining > 0:
        worker.join(remaining)
    if worker.is_alive():
        with lock:
            state["aborted"] = True
            socks_to_abort = list(state["socks"])
        for s in socks_to_abort:
            _shutdown_sock(s)
        _abort_response(state["resp"])
        worker.join(0.2)
        if state["http_err"] is not None:
            err_msg = b"".join(list(state["err_chunks"])).decode("utf-8", errors="replace")
            return None, state["http_err"], err_msg
        raise TimeoutError("LLM request exceeded %ss total timeout" % timeout)
    if state["aborted"] and state["body"] is None and state["http_err"] is None:
        raise TimeoutError("LLM request exceeded %ss total timeout" % timeout)
    if state["http_err"] is not None:
        err_msg = b"".join(list(state["err_chunks"])).decode("utf-8", errors="replace")
        return None, state["http_err"], err_msg
    if state["exc"] is not None:
        raise state["exc"]
    return state["body"], None, ""


def ask(prompt, audio_b64=None, max_tokens=800):
    content = [{"type": "text", "text": prompt}]
    if audio_b64:
        content.append({"type": "input_audio", "input_audio": {"data": audio_b64, "format": "mp3"}})
    timeout = int(config.LLM_TIMEOUT if isinstance(LLM_TIMEOUT, _ConfigTimeout) else LLM_TIMEOUT)
    last = None
    for pool_round in range(2):
        fast_failover = len(LLM_MODELS) > 1 and pool_round == 0
        for model in LLM_MODELS:
            payload = {"model": model, "messages": [{"role": "user", "content": content}],
                       "max_tokens": max_tokens, "temperature": 0}
            headers = {"Content-Type": "application/json", "User-Agent": "curl/8.4.0"}
            if LLM_KEY:
                headers["Authorization"] = "Bearer " + LLM_KEY
            body = None
            for attempt in range(4):
                try:
                    req = urllib.request.Request(LLM_URL, data=json.dumps(payload).encode(),
                                                headers=headers)
                    body, http_err, err_msg = _fetch_with_deadline(req, timeout)
                    if http_err is not None:
                        last = http_err
                        print("! llm %s (try %d/4 HTTP %s): %s | %s" % (model, attempt + 1, http_err.code, str(http_err)[:100], err_msg[:160]), flush=True)
                        if http_err.code == 429:
                            if "TPD" in err_msg or "tokens per day" in err_msg:
                                print("! model %s daily token limit exhausted, switching" % model, flush=True)
                                break
                            print("! model %s 429 RPM rate limited, backing off 8s..." % model, flush=True)
                            time.sleep(8 * (attempt + 1))
                        elif fast_failover:
                            print("! model %s HTTP %s, failing over to next model" % (model, http_err.code), flush=True)
                            break
                        elif attempt < 3:
                            time.sleep(2 * (attempt + 1))
                        continue
                    break
                except Exception as e:
                    last = e
                    print("! llm %s (try %d/4): %s" % (model, attempt + 1, str(e)[:140]), flush=True)
                    if fast_failover:
                        print("! model %s failed, failing over to next model" % model, flush=True)
                        break
                    if attempt < 3:
                        time.sleep(2 * (attempt + 1))
            if body is not None:
                break
        if body is not None:
            break
        if pool_round == 0:
            print("! pool exhausted on rate limit, backing off 8s before retry...", flush=True)
            time.sleep(8)
    if body is not None:
        if body.lstrip().startswith("data:"):
            out = []
            for line in body.splitlines():
                if not line.startswith("data: "):
                    continue
                d = line[6:]
                if d == "[DONE]":
                    break
                try:
                    out.append(json.loads(d)["choices"][0]["delta"].get("content") or "")
                except Exception:
                    pass
            return "".join(out)
        try:
            return json.loads(body)["choices"][0]["message"]["content"]
        except Exception as e:
            last = e
            print("! llm parse: %s" % str(e)[:140], flush=True)
    raise last if last else RuntimeError("llm failed")


def ask_json(prompt, audio_b64=None, max_tokens=800):
    txt = ask(prompt + "\n\nReply with JSON only, no prose, no code fences.", audio_b64, max_tokens)
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        return None
    try:
        return json.loads(txt[i:j + 1], strict=False)
    except Exception as e:
        print("! json: %s | raw=%r" % (str(e)[:80], txt[:120]), flush=True)
        return None



# ---------- blockers ----------
def neutralize(t):
    """Remove modal overlays that eat mouse events (they only block real input, JS clicks pass)."""
    return jso(t, """
      document.querySelectorAll('#colorbox, .colorbox').forEach(e=>e.remove());
      document.querySelectorAll('.modal-close, .modalW, .modal, .layout__alertModal, .modal-backdrop').forEach(e=>e.remove());
      document.body.classList.remove('modal-open');
      document.querySelectorAll('.utils__siteOverlay').forEach(e=>{e.style.pointerEvents='none';});
      const fb=document.getElementById('EdoFrameBox'); if(fb){fb.style.display='none';}
      return 1;
    """.strip())


def dialog_text(t):
    return t.js("""(() => {
      const out=[];
      document.querySelectorAll('iframe#colorBoxIframe').forEach(f=>{try{const d=f.contentDocument; if(d) out.push(d.body.innerText.trim().slice(0,120));}catch(e){}});
      return out;
    })()""")


def click_label_trusted(t, lbl_for):
    r = t.js("""(() => {const l=document.querySelector('.prMCQ__answerLabel[for=%s]'); if(!l) return null;
      const b=l.getBoundingClientRect(); return {x:Math.round(b.x+b.width/2), y:Math.round(b.y+b.height/2)};})()""" % json.dumps(lbl_for))
    if not r:
        return False
    t.click_xy(r["x"], r["y"])
    time.sleep(0.3)
    return True


def ensure_checked(t, lbl_for, tries=3):
    for _ in range(tries):
        ok = t.js("""(() => {
          const i = document.querySelector('.prMCQ__answerLabel[for=%s]');
          if (!i) return false;
          const inp = document.getElementById(i.getAttribute('for'));
          const p = i.closest('.prMCQ__answers');
          if (p) p.classList.add('prMCQ__answers--checked');
          if (inp && !inp.checked) {
            inp.checked = true;
            inp.dispatchEvent(new Event('change', { bubbles: true }));
          }
          return !!(inp && inp.checked);
        })()""" % json.dumps(lbl_for))
        if ok:
            return True
        click_label_trusted(t, lbl_for)
    return False

# ---------- page helpers ----------
def jso(t, expr):
    return t.js("(() => {" + expr + "})()")


def state(t):
    return t.js("""(() => {
      const dd=[...document.querySelectorAll('ed-la-dropdownlist')].map(d=>d.innerText.split('\\n')[0]);
      const c=document.querySelector('.learning__taskNavPCCurrentTask');
      const tot=document.querySelector('.learning__taskNavPCTotalTasks');
      return {url:location.href, lesson:dd[0]||'', step:dd[1]||'',
              counter:c?c.innerText.trim():null, total:tot?tot.innerText.trim():null};
    })()""")


def source_text(t):
    return t.js("""(() => {
      const r=document.querySelector('ed-la-resourcearea');
      const rt = r ? r.innerText.trim() : '';
      const b = document.body?.innerText || '';
      const i = b.indexOf('Back');
      return {resource: rt, body: b.slice(0, 6000)};
    })()""")


def dom_transcript(t):
    """Grab transcript directly from DOM if present (e.g. 'See Text' container)."""
    return t.js("""(() => {
      const el = document.querySelector('#textContainer, .seeTextContainer, .learning__RATextW');
      if (el && el.innerText && el.innerText.trim().length > 10) {
        return el.innerText.trim();
      }
      return null;
    })()""")


_TRANSCRIPT_BOUNDS = (
    ("AUDIO TRANSCRIPT:", "[/AUDIO TRANSCRIPT]"),
    ("[TRANSCRIPT]", "[/TRANSCRIPT]"),
)


def _extract_transcript_block(src: str) -> str:
    """Return the bounded transcript block if present and non-empty, else ''."""
    if not src:
        return ""
    for start_m, end_m in _TRANSCRIPT_BOUNDS:
        s_idx = src.find(start_m)
        if s_idx < 0:
            continue
        content_start = s_idx + len(start_m)
        e_idx = src.find(end_m, content_start)
        if e_idx < 0:
            continue
        if src[content_start:e_idx].strip():
            return src[s_idx:e_idx + len(end_m)]
    return ""


def _has_attached_transcript(src: str) -> bool:
    """True only when a bounded, non-empty transcript block is attached."""
    return bool(_extract_transcript_block(src))


def _format_transcript_block(text: str) -> str:
    return f"AUDIO TRANSCRIPT:\n{text.strip()}\n[/AUDIO TRANSCRIPT]"


def _media_cache_key(url: str) -> str:
    """Identify the full media URL without exposing credentials in cache names."""
    return hashlib.sha256(url.split("#", 1)[0].encode("utf-8")).hexdigest()


def attach_transcript(t, src, label="--", prefer_last_media=False):
    """Attach audio/video transcript from DOM or media ASR if not already in src."""
    if _has_attached_transcript(src):
        return src
    dt = dom_transcript(t)
    if dt:
        print(f"{label} dom-transcript ({len(dt)} chars)", flush=True)
        return (src or "") + "\n\n" + _format_transcript_block(dt)
    u = media_url(t, prefer_last=True) if prefer_last_media else media_url(t)
    if u:
        key = _media_cache_key(u)
        try:
            tr = transcript_for(u, key)
        except Exception:
            tr = ""
            print(f"! transcript {key}: unavailable", flush=True)
        if tr:
            print(f"{label} transcript {key} ({len(tr)} chars)", flush=True)
            return (src or "") + "\n\n" + _format_transcript_block(tr)
    return src


def resolve_task_transcript(t, base_src, activity_key, retained_state, label="--", prefer_last_media=False):
    """Attach transcript for the current task, retaining across questions in the same activity."""
    if retained_state.get("key") != activity_key:
        retained_state["key"] = activity_key
        retained_state["block"] = ""
        retained_state["media"] = None
    cur_media = media_url(t, prefer_last=True) if prefer_last_media else media_url(t)
    task_src = attach_transcript(t, base_src, label=label, prefer_last_media=prefer_last_media)
    block = _extract_transcript_block(task_src)
    if block:
        retained_state["block"] = block
        retained_state["media"] = cur_media
        return task_src
    if cur_media and cur_media != retained_state.get("media"):
        retained_state["block"] = ""
        retained_state["media"] = cur_media
        return task_src
    if retained_state.get("block"):
        return (base_src or "") + "\n\n" + retained_state["block"]
    return task_src


def play_media(t, timeout=45, quick=False):
    """Click play button and accelerate playback at 16x speed to complete and trigger server beacon."""
    present = t.js("""(() => [...document.querySelectorAll('audio,video')].filter(x=>(x.currentSrc||x.src)).length)()""")
    if not present:
        return False
    t.js("""(() => {
      window._mediaEndedLatched = false;
      const b=document.querySelector('.layout__mediaPlayPause');
      if(b) b.click();
      document.querySelectorAll('audio,video').forEach(m => {
        try {
          m.playbackRate = 16.0;
          m.addEventListener('ended', () => { window._mediaEndedLatched = true; }, { once: true });
        } catch(e){}
      });
      return 1;
    })()""")
    t0 = time.time()
    started = False
    while time.time() - t0 < timeout:
        time.sleep(0.5)
        st = t.js("""(() => {
          if (window._mediaEndedLatched) return 'ended';
          const a=[...document.querySelectorAll('audio,video')].filter(x=>(x.currentSrc||x.src));
          if(!a.length) return 'none';
          const el=a.sort((p,q)=>((q.duration||0)-(p.duration||0)))[0];
          try { el.playbackRate = 16.0; } catch(e){}
          if(el.ended || (el.duration && el.currentTime >= el.duration - 0.5)) return 'ended';
          if(el.currentTime > 0) return 'playing';
          return 'waiting';
        })()""")
        if st == "ended":
            return True
        if st == "playing":
            started = True
        elif started and st == "waiting":
            # Player finished and reset to 0
            return True
        if quick and (time.time() - t0 >= 4.0):
            return True
    return False


def media_url(t, prefer_last=False):
    pick_last = "1" if prefer_last else "0"
    return t.js(f"""(() => {{
      const isVis = el => !el.closest('.hide, [hidden]') && getComputedStyle(el).display !== 'none';
      const pick = list => list.map(x => x.currentSrc || x.src).filter(Boolean);
      const srcEls = [...document.querySelectorAll('audio,video')].filter(x => x.currentSrc || x.src);
      const visEls = srcEls.filter(isVis);
      const pool = visEls.length ? visEls : srcEls;
      const practice = pick(pool.filter(x => x.closest('ed-la-practicearea, #pmContainer')));
      const resource = pick(pool.filter(x => x.closest('ed-la-resourcearea')));
      const all = pick(pool);
      const urls = {pick_last}
        ? all
        : (practice.length ? practice : (resource.length ? resource : all));
      if (!urls.length) return null;
      return {pick_last} ? urls[urls.length - 1] : urls[0];
    }})()""")


def transcribe_groq(media_path: str) -> str:
    """Transcribe audio/video file via Groq Whisper API (fast & free)."""
    if not config.GROQ_API_KEY or not os.path.exists(media_path):
        return ""
    try:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        with open(media_path, "rb") as f:
            media_data = f.read()
        fname = os.path.basename(media_path)
        ext = os.path.splitext(fname)[1].lower().lstrip(".") or "mp3"
        mime = "video/mp4" if ext == "mp4" else ("audio/mpeg" if ext == "mp3" else f"audio/{ext}")
        body = bytearray()
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{config.GROQ_WHISPER_MODEL}\r\n".encode())
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fname}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        body.extend(media_data)
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        url = f"{config.GROQ_BASE_URL.rstrip('/')}/audio/transcriptions"
        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        resp = urllib.request.urlopen(req, timeout=45)
        res = json.loads(resp.read().decode())
        text = res.get("text", "").strip()
        if text:
            print(f"groq whisper transcribed ({len(text)} chars)", flush=True)
            return text
    except Exception as e:
        print(f"! groq whisper failed: {e}", flush=True)
    return ""


def _publish_transcript(destination, text):
    """Publish complete text once without overwriting a concurrent writer."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=SCRATCH,
                                         prefix=".transcript-", delete=False) as f:
            temp_path = f.name
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # A hard link publishes the completed inode atomically and fails if the
        # destination exists, including when another writer won the race.
        os.link(temp_path, destination)
    finally:
        if temp_path is not None:
            os.unlink(temp_path)


def migrate_legacy_transcript(url, legacy_path):
    """Copy a manually verified transcript to its URL-specific cache entry.

    The caller must establish provenance; legacy filenames do not prove it.
    Never overwrite an existing entry or remove the original.
    """
    with open(legacy_path, encoding="utf-8") as f:
        text = f.read()
    os.makedirs(SCRATCH, exist_ok=True)
    destination = os.path.join(SCRATCH, f"tr_{_media_cache_key(url)}.txt")
    _publish_transcript(destination, text)


def transcript_for(url, cache_key):
    os.makedirs(SCRATCH, exist_ok=True)
    # The caller's legacy key is not an identity; never trust it for disk access.
    cache_key = _media_cache_key(url)
    path = os.path.join(SCRATCH, f"tr_{cache_key}.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    # Extract file extension from URL
    ext = ".mp3"
    clean_url = url.split("#", 1)[0].split("?", 1)[0].lower()
    for e in [".mp4", ".m4a", ".wav", ".webm", ".mp3"]:
        if clean_url.endswith(e):
            ext = e
            break

    # Name-only legacy transcripts and media have no path provenance; leave them
    # untouched, but do not guess that they belong to this URL.

    media_file = os.path.join(SCRATCH, f"m_{cache_key}{ext}")
    if not os.path.exists(media_file):
        temp_path = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with tempfile.NamedTemporaryFile(dir=SCRATCH, prefix=".media-", delete=False) as f:
                temp_path = f.name
                f.write(data)
            os.replace(temp_path, media_file)
        except Exception:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            print(f"! failed to download media {cache_key}", flush=True)
            return ""

    if not os.path.exists(media_file):
        return ""

    # 1. Try Groq Whisper STT first if configured
    txt = transcribe_groq(media_file)

    # 2. Fall back to multimodal LLM input_audio if mp3
    if not txt and ext == ".mp3":
        with open(media_file, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        txt = ask("Transcribe this audio exactly. Output only the transcript.", audio_b64=b64, max_tokens=2000)

    if txt:
        try:
            _publish_transcript(path, txt)
        except FileExistsError:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    return txt


# ---------- task solvers ----------
def solve_mcq(t, src):
    sets = edlib.mcq_sets(t)
    picks = []
    for s in sets:
        prompt = (f"SOURCE MATERIAL:\n{src}\n\nQUESTION: {s['q']}\nOPTIONS:\n"
                  + "\n".join(f"- {o['t']}" for o in s["opts"])
                  + '\n\nPick the single correct option. Reply {"answer": "<exact option text>"}.')
        r = ask_json(prompt) or {}
        want = (r.get("answer") or "").strip().lower()
        o = next((x for x in s["opts"] if x["t"].strip().lower() == want), None)
        if not o:
            o = next((x for x in s["opts"] if want and want in x["t"].strip().lower()), None)
        if not o:
            o = s["opts"][0]
        edlib.click_for(t, o["for"])
        ensure_checked(t, o["for"])
        picks.append(o["t"][:40])
    return "mcq: " + " | ".join(picks)


def solve_multi(t, src):
    items = t.js("""(() => [...document.querySelectorAll('.lessonMultipleAnswer')].map(e=>({id:e.id, t:e.innerText.trim()})))()""")
    q = t.js("""(() => {const e=document.querySelector('.prMCQ__questionText, .learning__practiceQuestionText, .prMULTI__question');
      return e? e.innerText.trim() : '';})()""")
    header = t.js("""(() => {const p=document.querySelector('ed-la-practicearea'); return p? p.innerText.slice(0,200):'';})()""")
    prompt = (f"SOURCE MATERIAL:\n{src}\n\nTASK: {header}\n\nSTATEMENTS:\n"
              + "\n".join(f"{i+1}. {x['t']}" for i, x in enumerate(items))
              + '\n\nWhich statements are TRUE / correct? Reply {"true_indices": [1,3]} using 1-based numbers.')
    r = ask_json(prompt, max_tokens=1500) or {}
    idx = [i for i in r.get("true_indices", []) if isinstance(i, int) and 1 <= i <= len(items)]
    if not idx:
        idx = [1]
    for i in idx:
        el = items[i - 1]
        jso(t, f"const el=document.getElementById('{el['id']}'); if(el){{(el.querySelector('label')||el).click();}} return 1;")
        time.sleep(0.2)
    return "multi: " + ", ".join(items[i - 1]["t"][:30] for i in idx)


_BANK_ZONE = "TTpTablePlaceHolder"
_BANK_ZONE_SEL = f'.dndZone[dg_name="{_BANK_ZONE}"], .dndZone#{_BANK_ZONE}'
_DRAG_DROP_OFFSETS = ((0, 0), (-25, 0), (25, 0), (0, -4), (0, 4), (0, 8))


def _is_bank_zone(z):
    return isinstance(z, dict) and (z.get("n") == _BANK_ZONE or z.get("id") == _BANK_ZONE)


def _clamp_drop_offset(z, dx, dy, fallback_box=None):
    if dx:
        w = z.get("w") if z.get("w") is not None else z.get("width")
        if w is None and isinstance(fallback_box, dict):
            w = fallback_box.get("w")
        if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0:
            max_dx = max(0.0, w / 2.0 - min(4.0, w / 4.0))
            dx = max(-max_dx, min(max_dx, dx))
    return dx, dy


def _endpoints_reachable(item, tx, ty, meta):
    if not isinstance(meta, dict):
        return True
    if meta.get("sourceInView") is False or meta.get("targetInView") is False:
        return False
    vw, vh = meta.get("vw"), meta.get("vh")
    if isinstance(vw, (int, float)) and not isinstance(vw, bool) and vw > 0:
        if item["cx"] < 0 or item["cx"] >= vw or tx < 0 or tx >= vw:
            return False
    if isinstance(vh, (int, float)) and not isinstance(vh, bool) and vh > 0:
        if item["cy"] < 0 or item["cy"] >= vh or ty < 0 or ty >= vh:
            return False
    return True


def _too_far_for_offsets(item, z, meta):
    if not isinstance(meta, dict):
        return False
    if meta.get("unreachable") is True:
        return True
    vw, vh = meta.get("vw"), meta.get("vh")
    if isinstance(vh, (int, float)) and not isinstance(vh, bool) and vh > 0:
        if z["cy"] - 8 >= vh or z["cy"] + 8 < 0 or abs(z["cy"] - item["cy"]) > vh + 8:
            return True
    if isinstance(vw, (int, float)) and not isinstance(vw, bool) and vw > 0:
        if z["cx"] - 25 >= vw or z["cx"] + 25 < 0 or abs(z["cx"] - item["cx"]) > vw + 25:
            return True
    return False


def _scroll_drag_into_view(t, zone_sel, word, dx=0, dy=0):
    meta = t.js("""(() => {
      const want = %s.toLowerCase();
      const z = document.querySelector(%s);
      const reqDx = %s, reqDy = %s;
      const items = [...document.querySelectorAll('.dnditem')];
      const it = items.find(e => e.innerText.trim().toLowerCase() === want)
              || items.find(e => e.innerText.toLowerCase().includes(want));
      const vh = () => {
        const ih = window.innerHeight || 0;
        const ch = (document.documentElement && document.documentElement.clientHeight) || 0;
        return (ih > 0 && ch > 0) ? Math.min(ih, ch) : (ih || ch || 800);
      };
      const vw = () => {
        const iw = window.innerWidth || 0;
        const cw = (document.documentElement && document.documentElement.clientWidth) || 0;
        return (iw > 0 && cw > 0) ? Math.min(iw, cw) : (iw || cw || 1280);
      };
      const clipsAxis = val => /^(hidden|scroll|auto|clip)$/.test(val || '');
      const ancestorClipFlags = cur => {
        if (typeof window.getComputedStyle === 'function') {
          const cs = window.getComputedStyle(cur);
          if (cs && (cs.display === 'none' || cs.visibility === 'hidden')) return { hidden: true, cx: true, cy: true };
          return {
            hidden: false,
            cx: clipsAxis(cs && (cs.overflowX || cs.overflow)),
            cy: clipsAxis(cs && (cs.overflowY || cs.overflow))
          };
        }
        return {
          hidden: false,
          cx: (cur.clientWidth > 0 && cur.scrollWidth > cur.clientWidth) || clipsAxis(cur.overflowX || cur.overflow),
          cy: (cur.clientHeight > 0 && cur.scrollHeight > cur.clientHeight) || clipsAxis(cur.overflowY || cur.overflow)
        };
      };
      const visibleBoundsFor = el => {
        let left = 0, top = 0, right = vw(), bottom = vh();
        let cur = el ? el.parentElement : null;
        while (cur && cur !== document.documentElement) {
          const fl = ancestorClipFlags(cur);
          if (fl.hidden) return { left: 0, top: 0, right: 0, bottom: 0 };
          if ((fl.cx || fl.cy) && typeof cur.getBoundingClientRect === 'function') {
            const cr = cur.getBoundingClientRect();
            const cl = cr.left + (cur.clientLeft || 0);
            const ct = cr.top + (cur.clientTop || 0);
            const cRight = cur.clientWidth > 0 ? (cl + cur.clientWidth) : cr.right;
            const cBot = cur.clientHeight > 0 ? (ct + cur.clientHeight) : cr.bottom;
            if (fl.cx) { left = Math.max(left, cl); right = Math.min(right, cRight); }
            if (fl.cy) { top = Math.max(top, ct); bottom = Math.min(bottom, cBot); }
          }
          cur = cur.parentElement;
        }
        return { left, top, right, bottom };
      };
      const isPointVisible = (el, px, py) => {
        if (!el || typeof el.getBoundingClientRect !== 'function') return false;
        if (typeof window.getComputedStyle === 'function') {
          const es = window.getComputedStyle(el);
          if (es && (es.display === 'none' || es.visibility === 'hidden' || parseFloat(es.opacity) === 0)) return false;
        }
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return false;
        const b = visibleBoundsFor(el);
        if (b.right <= b.left || b.bottom <= b.top) return false;
        if (px < b.left || px >= b.right || py < b.top || py >= b.bottom) return false;
        const zx = r.width > 2 ? Math.max(r.left + 1, Math.min(r.right - 1, px)) : (r.left + r.width / 2);
        const zy = r.height > 2 ? Math.max(r.top + 1, Math.min(r.bottom - 1, py)) : (r.top + r.height / 2);
        if (zx < b.left || zx >= b.right || zy < b.top || zy >= b.bottom) return false;
        if (typeof document.elementFromPoint === 'function') {
          const hit = document.elementFromPoint(zx, zy);
          if (!hit) return false;
          if (hit !== el && !(typeof el.contains === 'function' && el.contains(hit))) return false;
        }
        return true;
      };
      const scrollByDelta = (el, dx, dy) => {
        let moved = false;
        let cur = el ? el.parentElement : null;
        while (cur && cur !== document.body && cur !== document.documentElement) {
          if (dy && cur.scrollHeight > cur.clientHeight) {
            const b = cur.scrollTop;
            cur.scrollTop += dy;
            if (cur.scrollTop !== b) moved = true;
          }
          if (dx && cur.scrollWidth > cur.clientWidth) {
            const b = cur.scrollLeft;
            cur.scrollLeft += dx;
            if (cur.scrollLeft !== b) moved = true;
          }
          cur = cur.parentElement;
        }
        if ((dx || dy) && typeof window.scrollBy === 'function') {
          const bx = window.scrollX || window.pageXOffset || 0;
          const by = window.scrollY || window.pageYOffset || 0;
          window.scrollBy(dx, dy);
          const ax = window.scrollX || window.pageXOffset || 0;
          const ay = window.scrollY || window.pageYOffset || 0;
          if (ax !== bx || ay !== by) moved = true;
        }
        return moved;
      };
      const evalEndpoints = () => {
        const ir = it ? it.getBoundingClientRect() : null;
        const zr = z ? z.getBoundingClientRect() : null;
        let cdx = reqDx, cdy = reqDy;
        if (cdx && zr && zr.width > 0) {
          const mx = Math.max(0, zr.width / 2 - Math.min(4, zr.width / 4));
          cdx = Math.max(-mx, Math.min(mx, cdx));
        }
        const sx = ir ? ir.left + ir.width / 2 : 0;
        const sy = ir ? ir.top + ir.height / 2 : 0;
        const tx = zr ? zr.left + zr.width / 2 + cdx : 0;
        const ty = zr ? zr.top + zr.height / 2 + cdy : 0;
        return {
          ir, zr, sx, sy, tx, ty,
          srcOk: it ? isPointVisible(it, sx, sy) : false,
          tgtOk: z ? isPointVisible(z, tx, ty) : false
        };
      };

      let ep = evalEndpoints();
      if (!it || !z || (ep.srcOk && ep.tgtOk)) {
        return {
          scrolled: 0,
          w: ep.zr ? ep.zr.width : null,
          h: ep.zr ? ep.zr.height : null,
          vw: vw(),
          vh: vh(),
          sourceInView: ep.srcOk,
          targetInView: ep.tgtOk,
          unreachable: (!it || !z) ? true : false
        };
      }

      let scrolled = 0;
      if (!ep.srcOk && typeof it.scrollIntoView === 'function') {
        it.scrollIntoView({block: 'nearest', inline: 'nearest'});
        scrolled = 1;
        ep = evalEndpoints();
      }
      if (!ep.tgtOk && typeof z.scrollIntoView === 'function') {
        z.scrollIntoView({block: 'nearest', inline: 'nearest'});
        scrolled = 1;
        ep = evalEndpoints();
      }
      if (!ep.srcOk || !ep.tgtOk) {
        let bLeft = 0, bTop = 0, bRight = vw(), bBot = vh();
        let anc = it ? it.parentElement : null;
        while (anc && anc !== document.documentElement) {
          if (typeof anc.contains === 'function' && anc.contains(z)) {
            const fl = ancestorClipFlags(anc);
            if ((fl.cx || fl.cy) && typeof anc.getBoundingClientRect === 'function') {
              const cr = anc.getBoundingClientRect();
              const cl = cr.left + (anc.clientLeft || 0), ct = cr.top + (anc.clientTop || 0);
              const cRight = anc.clientWidth > 0 ? (cl + anc.clientWidth) : cr.right;
              const cBot = anc.clientHeight > 0 ? (ct + anc.clientHeight) : cr.bottom;
              if (fl.cx) { bLeft = Math.max(bLeft, cl); bRight = Math.min(bRight, cRight); }
              if (fl.cy) { bTop = Math.max(bTop, ct); bBot = Math.min(bBot, cBot); }
            }
          }
          anc = anc.parentElement;
        }
        const availW = bRight - bLeft, availH = bBot - bTop;
        let dxS = 0, dyS = 0;
        if (availH > 0) {
          const minTop = Math.min(ep.ir.top, ep.zr.top), maxBot = Math.max(ep.ir.bottom, ep.zr.bottom);
          const minPy = Math.min(ep.sy, ep.ty), maxPy = Math.max(ep.sy, ep.ty);
          if (maxBot - minTop <= availH) {
            if (minTop < bTop) dyS = minTop - bTop;
            else if (maxBot > bBot) dyS = maxBot - bBot;
          } else if (maxPy - minPy <= availH - 2) {
            if (minPy < bTop + 1) dyS = minPy - (bTop + 1);
            else if (maxPy > bBot - 1) dyS = maxPy - (bBot - 1);
          }
        }
        if (availW > 0) {
          const minLeft = Math.min(ep.ir.left, ep.zr.left), maxRight = Math.max(ep.ir.right, ep.zr.right);
          const minPx = Math.min(ep.sx, ep.tx), maxPx = Math.max(ep.sx, ep.tx);
          if (maxRight - minLeft <= availW) {
            if (minLeft < bLeft) dxS = minLeft - bLeft;
            else if (maxRight > bRight) dxS = maxRight - bRight;
          } else if (maxPx - minPx <= availW - 2) {
            if (minPx < bLeft + 1) dxS = minPx - (bLeft + 1);
            else if (maxPx > bRight - 1) dxS = maxPx - (bRight - 1);
          }
        }
        const moved = (dxS || dyS) ? scrollByDelta(it, dxS, dyS) : false;
        if (moved) {
          scrolled = 1;
          ep = evalEndpoints();
        }
        if (!ep.srcOk && typeof it.scrollIntoView === 'function') {
          const fitsBoth = availH > 0 && availW > 0
            && (Math.max(ep.sy, ep.ty) - Math.min(ep.sy, ep.ty)) <= availH - 2
            && (Math.max(ep.sx, ep.tx) - Math.min(ep.sx, ep.tx)) <= availW - 2;
          if ((!moved && fitsBoth) || !ep.srcOk) {
            it.scrollIntoView({block: 'nearest', inline: 'nearest'});
            scrolled = 1;
            ep = evalEndpoints();
          }
        }
      }

      const tb = visibleBoundsFor(z);
      const zBoxCanReach = !!ep.zr && tb.right > tb.left && tb.bottom > tb.top
        && (ep.zr.right + 25) > tb.left && (ep.zr.left - 25) < tb.right
        && (ep.zr.bottom + 8) > tb.top && (ep.zr.top - 8) < tb.bottom;
      const unreachable = !ep.srcOk || (!ep.tgtOk && !zBoxCanReach);

      return {
        scrolled: scrolled,
        w: ep.zr ? ep.zr.width : null,
        h: ep.zr ? ep.zr.height : null,
        vw: vw(),
        vh: vh(),
        sourceInView: ep.srcOk,
        targetInView: ep.tgtOk,
        unreachable: unreachable
      };
    })()""" % (json.dumps(str(word).strip()), json.dumps(zone_sel), json.dumps(dx), json.dumps(dy)))
    if isinstance(meta, dict) and meta.get("scrolled") == 1:
        time.sleep(0.1)
    return meta if isinstance(meta, dict) else None


def _drag_snapshot(t):
    res = t.js("""(() => {
      const isBank = z => z.getAttribute('dg_name') === 'TTpTablePlaceHolder' || z.id === 'TTpTablePlaceHolder';
      const zones = [...document.querySelectorAll('.dndZone')].map(z => {
        let label = '';
        const row = z.closest('.prMT_T2T__answersRow, .prSeq__zone--txt, tr, .answersRow');
        if (row) {
          const lbl = row.querySelector('.prMT_T2T__answersText, .containerHeader, th, .label');
          if (lbl) label = lbl.innerText.trim();
        }
        return {
          n: z.getAttribute('dg_name'),
          id: z.id || '',
          label: label,
          items: [...z.querySelectorAll('.dnditem')].map(x => x.innerText.trim())
        };
      });
      const bank = [...document.querySelectorAll('.dndZone')]
        .filter(isBank)
        .flatMap(b => [...b.querySelectorAll('.dnditem')].map(x => x.innerText.trim()));
      return { zones: zones, bank: bank };
    })()""") or {}
    return res.get("zones", []), res.get("bank", [])


def solve_drag(t, src):
    zones, bank = _drag_snapshot(t)
    target_zones = [z for z in zones if not _is_bank_zone(z)]
    bank_sel = f'{_BANK_ZONE_SEL}, #{_BANK_ZONE}'
    if target_zones and all(z["items"] for z in target_zones):
        print("-- drag: zones pre-filled; clearing and re-dropping")
        moved_to_bank = False
        for z in target_zones:
            for item_text in z["items"]:
                bmeta = _scroll_drag_into_view(t, bank_sel, item_text)
                rr = edlib.rects(t)
                it = next((i for i in rr["items"] if i["t"].strip() == item_text.strip()), None)
                bz = next((zz for zz in rr["zones"] if _is_bank_zone(zz)), None)
                if not it or not bz or not _endpoints_reachable(it, bz["cx"], bz["cy"], bmeta):
                    continue
                t.drag_xy(it["cx"], it["cy"], bz["cx"], bz["cy"])
                moved_to_bank = True
                time.sleep(0.5)
        zones, bank = _drag_snapshot(t)
        target_zones = [z for z in zones if not _is_bank_zone(z)]
        if moved_to_bank and target_zones and all(z["items"] for z in target_zones):
            return "drag: already"
    prompt = t.js("""(() => {
      const p = document.querySelector('ed-la-matching, ed-la-practicearea, .learning__angPracticeW, .practicearea');
      return p ? p.innerText.slice(0, 2500) : '';
    })()""") or ""
    a_lines = [f"{i}. [id={z['n']}] {z.get('label') or ''} : {z['items'][0] if z['items'] else '(empty)'}" for i, z in enumerate(target_zones)]
    q = (f"SOURCE MATERIAL:\n{src}\n\nEXERCISE TEXT:\n{prompt}\n\n"
         f"Target blanks/topics (id, label, current):\n" + "\n".join(a_lines) +
         f"\n\nWord bank (to place):\n" + "\n".join(f"- {w}" for w in bank) +
         '\n\nMatch each blank id to the exact bank word/phrase that belongs there based on the material. '
         'Reply JSON only: {"map": {"0": "<exact bank word>", "1": "..."}}.')
    r = ask_json(q, max_tokens=2000)
    mapping = (r or {}).get("map", {})
    if not mapping:
        print("-- drag LLM empty; retrying")
        r = ask_json(q, max_tokens=2000)
        mapping = (r or {}).get("map", {})
    if not mapping:
        return "other: drag: EMPTY-MAP"
    # clear zones whose current item is not the desired one
    for zid, word in mapping.items():
        zid = str(zid)
        if _is_bank_zone({"n": zid, "id": zid}):
            continue
        cur = t.js(f"""(() => {{const z=document.querySelector('.dndZone[dg_name="{zid}"]'); return z? [...z.querySelectorAll('.dnditem')].map(x=>x.innerText.trim()):[];}})()""")
        for item_text in (cur or []):
            if str(word).strip().lower() in item_text.lower():
                continue
            for _ in range(3):
                bmeta = _scroll_drag_into_view(t, bank_sel, item_text)
                rr = edlib.rects(t)
                it = next((i for i in rr["items"] if i["t"].strip() == item_text.strip()), None)
                bz = next((z for z in rr["zones"] if _is_bank_zone(z)), None)
                if not it or not bz or not _endpoints_reachable(it, bz["cx"], bz["cy"], bmeta):
                    break
                t.drag_xy(it["cx"], it["cy"], bz["cx"], bz["cy"])
                time.sleep(0.7)
                break
    done = []
    for zid, word in mapping.items():
        zid = str(zid)
        if _is_bank_zone({"n": zid, "id": zid}):
            continue
        ok = False
        unreachable = False
        zone_sel = f'.dndZone[dg_name="{zid}"]'
        for dx, dy in _DRAG_DROP_OFFSETS:
            meta = _scroll_drag_into_view(t, zone_sel, word, dx=dx, dy=dy)
            rects = edlib.rects(t)
            item = next((i for i in rects["items"] if i["t"].strip().lower() == str(word).strip().lower()), None)
            if not item:
                item = next((i for i in rects["items"] if str(word).strip().lower() in i["t"].lower()), None)
            z = next((x for x in rects["zones"] if x["n"] == zid), None)
            if not item or not z:
                break
            cdx, cdy = _clamp_drop_offset(z, dx, dy, fallback_box=meta)
            tx, ty = z["cx"] + cdx, z["cy"] + cdy
            if not _endpoints_reachable(item, tx, ty, meta):
                unreachable = True
                if _too_far_for_offsets(item, z, meta):
                    break
                continue
            unreachable = False
            t.drag_xy(item["cx"], item["cy"], tx, ty)
            time.sleep(0.8)
            now = t.js(f"""(() => {{const z=document.querySelector('.dndZone[dg_name="{zid}"]');
              return z? [...z.querySelectorAll('.dnditem')].map(x=>x.innerText.trim()):[];}})()""")
            if any(str(word).strip().lower() in x.lower() for x in (now or [])):
                ok = True
                break
        status = "ok" if ok else ("UNREACHABLE" if unreachable else "FAIL")
        done.append(f"{zid}={status}")

    summary = "drag: " + " ".join(done)
    if not done or any(not d.endswith("=ok") for d in done):
        return "other: " + summary
    return summary




def solve_sequence(t, src):
    """Dialogue / chronological sequence: reorder items across dndZones."""
    neutralize(t)
    jso(t, "document.body.style.zoom='0.8'; return 1;")
    time.sleep(0.5)

    raw = t.js("""(() => {
      const zones = [...document.querySelectorAll('.sequenceZone .dndZone, .prSeq__zone--txt .dndZone, .dndZone')];
      const unique = [];
      const seen = new Set();
      for (const z of zones) {
        const n = z.getAttribute('dg_name');
        if (!n || n === 'TTpTablePlaceHolder' || z.id === 'TTpTablePlaceHolder' || seen.has(n)) continue;
        seen.add(n);
        const item = z.querySelector('.dnditem');
        unique.push({
          zone: n,
          text: (item ? item.innerText : z.innerText || '').trim()
        });
      }
      return unique;
    })()""")

    if not raw or len(raw) < 2:
        return "sequence: no-items"

    prompt_items = "\n".join(f"{i+1}. {x['text']}" for i, x in enumerate(raw))
    q = (f"SOURCE MATERIAL / CONTEXT:\n{src}\n\n"
         f"TASK: Put the following items in the correct order (dialogue, chronological events, or logical order).\n\n"
         f"ITEMS:\n{prompt_items}\n\n"
         f"Reply with JSON: {{\"order\": [1, 2, ...]}} listing the 1-based indices of the items in their correct sequential order.")

    r = ask_json(q, max_tokens=1000)
    order = (r or {}).get("order", [])
    if not order or len(order) != len(raw):
        print("-- sequence LLM invalid order, retrying")
        r = ask_json(q, max_tokens=1000)
        order = (r or {}).get("order", [])
    if not order:
        return "sequence: EMPTY-ORDER"

    target_texts = []
    for idx in order:
        if isinstance(idx, int) and 1 <= idx <= len(raw):
            target_texts.append(raw[idx - 1]["text"])
        else:
            return "sequence: INVALID-INDICES"

    neutralize(t)
    for pos, text in enumerate(target_texts):
        prefix = text[:30].strip()
        for _ in range(3):
            # Check if this zone already has the correct item
            already = t.js(f"""(() => {{
              const z = document.querySelector('.dndZone[dg_name="{pos}"]');
              const it = z ? z.querySelector('.dnditem') : null;
              return it && it.innerText.toLowerCase().includes({json.dumps(prefix.lower())}) ? 1 : 0;
            }})()""")
            if already:
                break
            rr = edlib.rects(t)
            item = next((x for x in rr["items"] if x["t"].startswith(prefix) or prefix in x["t"]), None)
            zone = next((x for x in rr["zones"] if x["n"] == str(pos)), None)
            if not item or not zone:
                break
            t.drag_xy(item["cx"], item["cy"], zone["cx"], zone["cy"] + 25)
            time.sleep(0.8)
            neutralize(t)

    return "sequence: ok"



def solve_cloze(t, src):
    """Legacy cloze: .draggable.wordBankTile -> .TTpanswerDiv droptargets."""
    jso(t, "document.body.style.zoom='0.85'; return 1;")
    time.sleep(0.8)
    data = t.js("""(() => {
      const targets=[...document.querySelectorAll('.TTpanswerDiv')].map((el,i)=>{
        let p=el.closest('.TextDiv')||el.parentElement;
        return {i:i, sentence:(p? p.innerText:'').trim().slice(0,300)};
      });
      const items=[...document.querySelectorAll('.draggable.wordBankTile')].map(el=>el.innerText.trim()).filter(Boolean);
      return {targets, items};
    })()""")
    targets = data["targets"] or []
    items = data["items"] or []
    if not targets or not items:
        return "cloze: no-targets"
    lines = "\n".join(f'{x["i"]}. "{x["sentence"]}"' for x in targets)
    r = ask_json(f"SOURCE MATERIAL:\n{src}\n\nGapped sentences (the gap is where a word must go):\n{lines}\n\n"
                 f"Word bank:\n" + "\n".join(f"- {w}" for w in items) +
                 '\n\nFor each sentence index pick the exact bank word. Reply {"map": {"0": "<word>", ...}}.', max_tokens=1500) or {}
    mapping = r.get("map", {})
    done = []
    for k, word in mapping.items():
        i = int(k)
        ok = False
        for _ in range(3):
            rects = t.js("""(() => {
              const el=document.querySelectorAll('.TTpanswerDiv')[%d];
              if(!el) return null; const b=el.getBoundingClientRect();
              return {x:b.x+b.width/2, y:b.y+b.height/2};
            })()""" % i)
            tile = t.js("""(() => {const els=[...document.querySelectorAll('.draggable.wordBankTile')];
              const el=els.find(e=>e.innerText.trim().toLowerCase()===%s.toLowerCase()) || null;
              if(!el) return null; const b=el.getBoundingClientRect();
              return {x:b.x+b.width/2, y:b.y+b.height/2};})()""" % json.dumps(word))
            if not rects or not tile:
                break
            t.drag_xy(tile["x"], tile["y"], rects["x"], rects["y"])
            time.sleep(0.6)
            txt = t.js("""(() => {const el=document.querySelectorAll('.TTpanswerDiv')[%d]; return el? el.innerText.trim():'';})()""" % i)
            if txt and txt.strip().lower().startswith(str(word).strip().lower()[:4]):
                ok = True
                break
        done.append(f"{i}={'ok' if ok else 'FAIL'}")
    return "cloze: " + " ".join(done)



def solve_cloze_legacy(t, src):
    """Old TTp cloze: jQuery 'drop' trigger with a bank tile element."""
    data = t.js("""(() => ({
      targets:[...document.querySelectorAll('.TTpanswerDiv')].map(e=>({id:e.getAttribute('data-id'),
        ctx:((e.closest('.TextDiv')||e.parentElement||e).innerText||'').replace(/\\s+/g,' ').trim().slice(0,300)})),
      bank:[...document.querySelectorAll('.draggable.wordBankTile')].map(e=>({id:jQuery(e.closest('.draggable')).data('id'), t:e.innerText.trim()}))
    }))()""")
    targets, bank = data["targets"], data["bank"]
    if not targets or not bank:
        return "lcloze: none"
    lines = "\n".join(f'- [{x["id"]}] "..."{x["ctx"][-160:]}' for x in targets)
    r = ask_json(f"SOURCE MATERIAL:\n{src}\n\nSentences with one gap (gap shown as blank):\n{lines}\n\n"
                 f"Word bank:\n" + "\n".join(f"- {w['t']}" for w in bank) +
                 '\n\nChoose the word for each sentence. Reply {"map": {"<target id>": "<exact bank word>"}}.', max_tokens=1200) or {}
    mapping = r.get("map", {})
    done = []
    for tid, word in mapping.items():
        w = next((b for b in bank if b["t"].strip().lower() == str(word).strip().lower()), None)
        if not w:
            done.append(f"{tid}=nw")
            continue
        ok = t.js("""(() => {const tgt=document.querySelector('.TTpanswerDiv[data-id="%s"]');
          const el=jQuery('.draggable[data-id=%s]')[0];
          if(!tgt||!el) return false; jQuery(tgt).triggerHandler('drop', [el]);
          return tgt.getAttribute('ans')==='%s';})()""" % (tid, w["id"], str(w["id"])))
        done.append(f"{tid}={'ok' if ok else 'FAIL'}")
    return "lcloze: " + " ".join(done)


def solve_writing(t, src, task_text):
    r = ask_json(f"SOURCE MATERIAL:\n{src}\n\nTASK:\n{task_text}\n\n"
                 'Write a natural 100-140 word response in the required role. Reply {"text": "..."}.')
    text = (r or {}).get("text") or "I am writing to provide feedback on this topic based on the course materials."
    if len(text.split()) < 5:
        text = "I am writing to share my thoughts and insights regarding the material covered in this unit."

    # TinyMCE editor
    jso(t, """const ed=window.tinymce&&tinymce.activeEditor; if(ed){ed.setContent(%s); ed.save();
      ['keyup','input','change'].forEach(ev=>{try{ed.fireEvent(ev,{});}catch(e){}
        const b=ed.getBody(); b.dispatchEvent(ev==='input'? new InputEvent('input',{bubbles:true}) : new KeyboardEvent(ev,{bubbles:true}));});
      try{ed.nodeChanged();}catch(e){} return 1;} return 0;""" % json.dumps(text))

    # Standard textarea / Angular writing area
    jso(t, """(() => {
      const ta = document.querySelector('.writingEditFrame textarea, textarea.writingTextarea, textarea');
      if (ta) {
        ta.focus();
        ta.value = %s;
        ['input', 'change', 'keyup'].forEach(ev => ta.dispatchEvent(new Event(ev, {bubbles: true})));
        return 1;
      }
      return 0;
    })()""" % json.dumps(text))
    time.sleep(1.0)
    jso(t, """(() => {
      const b=[...document.querySelectorAll('a,button,div,span')].filter(e=>(e.innerText||'').trim()==='Done');
      if(b.length){b[b.length-1].click(); return 1;}
      const el = document.querySelector('.prWriting__action--submit');
      if(el){ el.click(); return 1; }
      return 0;
    })()""")
    time.sleep(1.2)
    jso(t, """(() => {
      const ifr = document.querySelector('iframe#colorBoxIframe');
      const doc = ifr && ifr.contentDocument ? ifr.contentDocument : document;
      const btns = Array.from(doc.querySelectorAll('button, input[type=button], input[type=submit], a.button, .button, #btnOk, .prWriting__modalBtn'));
      const target = btns.find(b => /^(ok|continue|submit|yes|confirm)$/i.test((b.innerText || b.value || '').trim()));
      if (target) { target.click(); return 1; }
      return 0;
    })()""")
    time.sleep(1.0)
    words = jso(t, "const m=document.body.innerText.match(/Words: \\\\d+/); return m?m[0]:'';")
    return f"write: {words}"


def task_text(t):
    res = t.js("""(() => {const p=document.querySelector('ed-la-practicearea');
      return p? p.innerText.slice(0,1200):'';})()""")
    return str(res or "")



def solve_openended(t, src=""):
    """Vocabulary open-ended items: type the model answer into each textarea.

    Must go through Input.insertText (real typing) after focus(): assigning
    .value directly leaves the Angular model untouched, so the activity never
    registers and the step stays blocked.
    """
    data = t.js("""(() => {const el=document.querySelector('.learning__angPracticeW ng-component');
      if(!el) return null; const c=ng.probe(el).componentInstance; const qa=c.questionAnswers||{};
      const out=[]; Object.keys(qa).forEach(q=>{Object.keys(qa[q]).forEach(a=>{
        const box=qa[q][a]; out.push({id:'#prOpenEnded__qaItemText--qId_'+q+'_alId_'+a,
          txt:(box.answers&&box.answers[0]&&box.answers[0].txt)||''}); });});
      return out;})()""")
    if not data:
        return "open: nodata"
    ok = 0
    for item in data:
        if not item["txt"]:
            continue
        focused = jso(t, f"const ta=document.querySelector({json.dumps(item['id'])}); if(!ta) return 0; ta.focus(); return 1;")
        if not focused:
            continue
        t.send("Input.insertText", text=item["txt"])
        time.sleep(0.2)
        # Angular's open-ended component only marks the activity done from its
        # (keyup) handler, so fire one after the model has the text.
        jso(t, "const ta=document.querySelector(" + json.dumps(item["id"]) +
            "); if(ta) ta.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true})); return 1;")
        time.sleep(0.2)
        ok += 1
    jso(t, "document.body.focus(); if(document.activeElement) document.activeElement.blur(); return 1;")
    return f"open: {ok}"


ERRFIX_EXTRACT_JS = """(() => {
  const frame = document.querySelector('.writingEditFrame');
  if (!frame) return null;
  const box = frame.querySelector('.writingEditPracticeWrapper') || frame;
  const fields = [...box.querySelectorAll('input[type=text], textarea')];
  if (!fields.length) return null;
  const clone = box.cloneNode(true);
  const cloned = [...clone.querySelectorAll('input[type=text], textarea')];
  cloned.forEach((el, i) => {
    const s = document.createElement('span');
    s.textContent = '[[' + (i + 1) + ']]';
    el.replaceWith(s);
  });
  const ctx = (clone.innerText || clone.textContent || '').replace(/\\s+/g, ' ').trim();
  const errs = [...frame.querySelectorAll('.writingEditResourceSide .et')]
    .map(e => (e.innerText || '').trim()).filter(Boolean);
  const instEl = document.querySelector('.learning__taskInstruction');
  const inst = instEl ? (instEl.innerText || '').trim() : '';
  let answers = null;
  let hasItem = false;
  try {
    const item = window.$ ? $(fields[0]).data('OEItem') : null;
    hasItem = !!item;
    const q = item && item.json && item.json.q && item.json.q[0];
    if (q && q.al && q.al.length === fields.length) {
      answers = q.al.map(al => {
        const list = al.a || [];
        const correct = list.find(x => x.id !== 1001) || list[1];
        return correct ? correct.txt : '';
      });
    }
  } catch (e) {}
  return {
    ctx: ctx.slice(0, 2500),
    errs: errs,
    inst: inst.slice(0, 800),
    vals: fields.map(f => f.value || ''),
    answers: answers,
    hasItem: hasItem,
    count: fields.length
  };
})()"""

ERRFIX_FIELDS = (".writingEditFrame .writingEditPracticeWrapper input[type=text], "
                 ".writingEditFrame .writingEditPracticeWrapper textarea")

ERRFIX_VERIFY_JS = """(() => {
  const dd = document.querySelectorAll('ed-la-dropdownlist')[1];
  const comp = dd ? window.ng?.probe?.(dd)?.componentInstance : null;
  let prog = null;
  const node = comp?.dropDownListObj?.SelectedNode;
  if (node) prog = Number(node.Progress);
  if (prog === null) {
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    const n = app?.navigationService?._stepsList?.SelectedNode;
    if (n) prog = Number(n.Progress);
  }
  let done = null;
  const box = document.querySelector('.writingEditFrame');
  if (box) {
    const c = window.ng?.probe?.(box)?.componentInstance;
    if (c && 'doneProgress' in c) done = !!c.doneProgress;
  }
  return {prog: prog, done: done};
})()"""


def _errorfix_check_js(fn: str) -> str:
    return """(() => {
      const el = document.querySelector(%s);
      const item = window.$ && el ? $(el).data('OEItem') : null;
      if (item && typeof item.%s === 'function') { item.%s(); return 1; }
      return 0;
    })()""" % (json.dumps(ERRFIX_FIELDS), fn, fn)


def solve_errorfix(t, src=""):
    """Two-sided error-correction e-mail: inputs are pre-filled with wrong words.

    The legacy (non-Angular) widget stores each item in jQuery data `OEItem`.
    Correct answers live in `OEItem.json.q[0].al[i].a` (index 0 is the wrong
    word, index >= 1 is correct). Updating the DOM alone does nothing: the
    values must be pushed through the jQuery `change` handler, then
    `item.checkAnswer()` validates and registers step progress.
    """
    data = t.js(ERRFIX_EXTRACT_JS)
    if not data or not data.get("count"):
        return "errorfix: nodata"

    vals = data.get("vals") or []
    ctx = data.get("ctx") or ""
    errs = data.get("errs") or []
    inst = data.get("inst") or ""
    answers = data.get("answers") or []

    # Prefer answers embedded in the legacy item; only ask the LLM when absent.
    if len(answers) != len(vals):
        wrong = "\n".join(f"{i + 1}. {v!r}" for i, v in enumerate(vals))
        prompt = (
            "TASK: Correct the errors in this e-mail.\n"
            f"INSTRUCTION:\n{inst or (src or '')[-800:]}\n\n"
            f"E-MAIL WITH NUMBERED ERRORS:\n{ctx}\n\n"
            f"CURRENT (WRONG) WORDS:\n{wrong}\n\n"
            + (("HIGHLIGHTED ERRORS:\n" + "\n".join(f"- {e}" for e in errs) + "\n\n") if errs else "")
            + 'Replace every [[n]] with the correct word(s). Reply ONLY JSON mapping '
              'each number to the corrected text: {"1": "...", "2": "..."}'
        )
        picks = ask_json(prompt, max_tokens=500) or {}
        answers = [picks.get(str(i + 1)) or picks.get(i + 1) or "" for i in range(len(vals))]

    filled = 0
    for i, want in enumerate(answers):
        want = str(want or "").strip()
        if not want or want == vals[i]:
            continue
        ok = jso(t, """const el=document.querySelectorAll(%s)[%d];
          if(!el) return 0;
          const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          setter.call(el, %s);
          if (window.$) $(el).trigger('change');
          else el.dispatchEvent(new Event('change', {bubbles:true}));
          return 1;""" % (json.dumps(ERRFIX_FIELDS), i, json.dumps(want)))
        if ok:
            filled += 1
        time.sleep(0.1)

    # Legacy checker: adds vCheck/xCheck and persists task progress.
    jso(t, _errorfix_check_js("checkAnswer"))

    state = {}
    for _ in range(12):
        time.sleep(0.5)
        state = t.js(ERRFIX_VERIFY_JS) or {}
        prog = state.get("prog")
        if state.get("done") is True or (
            isinstance(prog, (int, float)) and not isinstance(prog, bool) and prog >= 0.999
        ):
            break

    prog = state.get("prog")
    if not (isinstance(prog, (int, float)) and not isinstance(prog, bool) and prog >= 0.999):
        # Some legacy variants only persist on unload.
        jso(t, _errorfix_check_js("onItemUnloaded"))
        time.sleep(1.0)
        state = t.js(ERRFIX_VERIFY_JS) or state

    return (f"errorfix: {filled}/{len(vals)} prog={state.get('prog')} "
            f"done={state.get('done')}")


_DDL_CARETS = "\u25be\u25bc\u25b4\u25b2\u2304\u2303\u2228\u2227"


def _norm_ddl(text, strip_punct=False):
    s = str(text or "")
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")):
        s = s.replace(a, b)
    if strip_punct:
        s = "".join(ch if ch.isalnum() else " " for ch in s)
    return " ".join(s.split()).lower()


def _norm_ddl_selected(text):
    s = str(text or "")
    for ch in _DDL_CARETS:
        s = s.replace(ch, " ")
    return _norm_ddl(s)


def _strip_ddl_prefix(text):
    s = str(text or "").strip().strip('"\'`')
    if s.startswith(("- ", "\u2022 ", "* ")):
        return s[2:].strip().strip('"\'`')
    i = 1 if s.startswith("(") else 0
    j = i
    while j < len(s) and s[j].isdigit():
        j += 1
    if j > i and j < len(s) and s[j] in ".)_:-" and s[j + 1:j + 2].isspace():
        return s[j + 2:].strip().strip('"\'`')
    return s


def _match_ddl_option(want, options):
    raw_want = str(want or "").strip()
    if not raw_want or not options:
        return None
    valid = []
    for idx, opt in enumerate(options):
        if isinstance(opt, dict):
            if opt.get("placeholder"):
                continue
            txt = str(opt.get("text") or "").strip()
        else:
            txt = str(opt or "").strip()
        if txt:
            valid.append((idx, txt))
    if not valid:
        return None

    for candidate in dict.fromkeys((raw_want, _strip_ddl_prefix(raw_want))):
        if not candidate:
            continue
        for idx, opt in valid:
            if opt == candidate:
                return idx
        w_norm = _norm_ddl(candidate)
        if w_norm:
            for idx, opt in valid:
                if _norm_ddl(opt) == w_norm:
                    return idx
        w_alnum = _norm_ddl(candidate, strip_punct=True)
        if w_alnum:
            for idx, opt in valid:
                if _norm_ddl(opt, strip_punct=True) == w_alnum:
                    return idx

    for strip_p in (False, True):
        w = _norm_ddl(_strip_ddl_prefix(raw_want), strip_punct=strip_p)
        if not w:
            continue
        scored = []
        for idx, opt in valid:
            o = _norm_ddl(opt, strip_punct=strip_p)
            if not o:
                continue
            padded_o, padded_w = f" {o} ", f" {w} "
            if padded_w in padded_o:
                scored.append((4, len(w), -len(o), -idx, idx))
            elif padded_o in padded_w:
                scored.append((3, len(o), 0, -idx, idx))
        if scored:
            return max(scored)[-1]
    return None


def _match_ddl_exact(target, options):
    tgt = _norm_ddl_selected(target)
    if not tgt or not options:
        return None
    for idx, opt in enumerate(options):
        if isinstance(opt, dict):
            if opt.get("placeholder"):
                continue
            txt = str(opt.get("text") or "").strip()
        else:
            txt = str(opt or "").strip()
        if txt and _norm_ddl_selected(txt) == tgt:
            return idx
    return None


def _ddl_selected_ok(selected_text, target_text, is_placeholder=False):
    if is_placeholder:
        return False
    sel = _norm_ddl_selected(selected_text)
    tgt = _norm_ddl_selected(target_text)
    if not sel or not tgt:
        return False
    return sel == tgt


_FITB_DOM_JS = r"""
  const CONTAINER_SEL = '.DDLOptionsW, .prFITB__DDLOptionsW, .prDDL__DDLOptionsW, .prFITB__qaItem, .prDDL__qaItem, .fitb-ddl';
  const OPT_SEL = '.DDLOptions__listItem, .DDLOptions__list li, .DDLOptions__option';
  const hasAttr = (el, name) => !!(el && el.hasAttribute && el.hasAttribute(name));
  const getAttr = (el, name) => (el && el.getAttribute) ? el.getAttribute(name) : null;
  const getOptText = (el) => ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g, ' ').trim();
  const isOptionPlaceholder = (el) => {
    if (!el) return true;
    if (el.disabled === true || hasAttr(el, 'disabled')) return true;
    if (String(getAttr(el, 'aria-disabled') || '').toLowerCase() === 'true') return true;
    if (hasAttr(el, 'data-placeholder') && String(getAttr(el, 'data-placeholder') || '').toLowerCase() !== 'false') return true;
    const role = String(getAttr(el, 'role') || '').toLowerCase();
    if (role === 'presentation' || role === 'separator') return true;
    const cls = String(el.className || '');
    if (/(?:^|[\s_-])(placeholder|disabled)(?:$|[\s_-])/i.test(cls)) return true;
    if (el.querySelector && el.querySelector('[disabled], [aria-disabled="true"], [data-placeholder]:not([data-placeholder="false"]), [class*="placeholder"]')) {
      return true;
    }
    return false;
  };
  const isVisible = (el) => {
    if (!el) return false;
    const hasLayout = !!(typeof document !== 'undefined' && document.body && document.body.getBoundingClientRect &&
      (document.body.getBoundingClientRect().width > 0 || document.body.getBoundingClientRect().height > 0));
    let cur = el;
    while (cur && cur.nodeType === 1) {
      if (cur.hidden || hasAttr(cur, 'hidden')) return false;
      const cls = cur.classList;
      if (cls && (cls.contains('hide') || cls.contains('ng-hide') || cls.contains('hidden') || cls.contains('DDLOptions__list--closed'))) return false;
      const st = (typeof window !== 'undefined' && window.getComputedStyle) ? window.getComputedStyle(cur) : cur.style;
      if (st && (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0')) return false;
      if (hasLayout && st && st.overflow === 'hidden' && cur.getBoundingClientRect) {
        const cr = cur.getBoundingClientRect();
        if (cr.width === 0 || cr.height === 0) return false;
      }
      cur = cur.parentElement;
    }
    if (hasLayout && el.getBoundingClientRect) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
    }
    return true;
  };
  const getTriggers = () => {
    const root = document.querySelector('.learning__angPracticeW, ed-la-practicearea, #pmContainer') || document;
    let sels = [...root.querySelectorAll('.DDLOptions__selected')];
    if (!sels.length) sels = [...document.querySelectorAll('.DDLOptions__selected')];
    if (!sels.length) {
      sels = [...document.querySelectorAll(CONTAINER_SEL)]
        .map(w => w.querySelector('.DDLOptions__selected'))
        .filter(Boolean);
    }
    const vis = sels.filter(isVisible);
    return vis.length ? vis : sels;
  };
  const getTrigger = (idx) => getTriggers()[idx] || null;
  const getContainers = (s) => {
    const out = [];
    let cur = s ? s.parentElement : null;
    while (cur && cur !== document.body && cur !== document.documentElement) {
      if (cur.matches && cur.matches(CONTAINER_SEL) && cur.querySelectorAll('.DDLOptions__selected').length <= 1) {
        out.push(cur);
      }
      cur = cur.parentElement;
    }
    return out;
  };
  const getPortalOwner = (el) => {
    const allTriggers = getTriggers();
    if (!allTriggers.length) return null;
    // An ARIA active descendant identifies a list even when that list has no
    // id. Require one unique option id within one recognized menu and collect
    // all claims together, so conflicting references remain ambiguous.
    const MENU_SEL = '.DDLOptions__list, [role="listbox"]';
    const menu = el.closest && el.closest(MENU_SEL);
    const menuOptions = menu ? [...menu.querySelectorAll(OPT_SEL)]
      .filter(option => option.closest && option.closest(MENU_SEL) === menu) : [];
    const idCounts = new Map();
    for (const item of document.querySelectorAll('[id]')) {
      const id = String(item.id || '');
      if (id) idCounts.set(id, (idCounts.get(id) || 0) + 1);
    }
    const broadPortalIds = new Set();
    const broadLabelledBy = new Set();
    let anc = el;
    const portalIds = new Set();
    const labelledBy = new Set();
    while (anc && anc !== document.body && anc !== document.documentElement) {
      // A link to an overlay containing multiple independent lists does not
      // establish which one belongs to the trigger. Do not promote that broad
      // relation to every child; a specific active-descendant may still do so.
      const groups = new Set([...anc.querySelectorAll(OPT_SEL)].map(option => {
        const group = option.closest && option.closest(MENU_SEL);
        return group && anc.contains(group) ? group : option.parentElement;
      }));
      const unambiguous = groups.size <= 1;
      if (anc.id && idCounts.get(String(anc.id)) === 1)
        (unambiguous ? portalIds : broadPortalIds).add(String(anc.id));
      for (const attr of ['aria-labelledby', 'data-trigger', 'data-for', 'data-owner', 'data-ddl-for']) {
        const v = getAttr(anc, attr);
        if (v) String(v).split(/\s+/).filter(Boolean).forEach(x =>
          (unambiguous ? labelledBy : broadLabelledBy).add(x.replace(/^#/, '')));
      }
      anc = anc.parentElement;
    }
    const owners = new Set();
    const broadOwners = new Set();
    for (const trig of allTriggers) {
      const scopes = [trig, ...getContainers(trig)];
      for (const sc of scopes) {
        const active = getAttr(sc, 'aria-activedescendant');
        if (active && idCounts.get(String(active)) === 1 &&
            menuOptions.some(option => String(option.id || '') === String(active))) owners.add(trig);
        if (sc && sc.id && idCounts.get(String(sc.id)) === 1) {
          if (labelledBy.has(String(sc.id))) owners.add(trig);
          if (broadLabelledBy.has(String(sc.id))) broadOwners.add(trig);
        }
        for (const attr of ['aria-controls', 'aria-owns', 'data-target', 'data-dropdown', 'data-menu', 'data-portal']) {
          const raw = getAttr(sc, attr);
          if (!raw) continue;
          for (const tok of String(raw).split(/\s+/).filter(Boolean)) {
            const id = tok.replace(/^#/, '');
            if (portalIds.has(id)) owners.add(trig);
            if (broadPortalIds.has(id)) broadOwners.add(trig);
          }
        }
      }
    }
    if (owners.size !== 1) return null;
    const owner = [...owners][0];
    return [...broadOwners].every(trig => trig === owner) ? owner : null;
  };
  const dedupOptions = (nodes) => {
    const arr = [...nodes];
    return arr.filter(el => !arr.some(other => other !== el && el.contains && el.contains(other)));
  };
  const selectableOptions = (nodes) => dedupOptions(nodes).filter(el => !isOptionPlaceholder(el) && getOptText(el) !== '');
  const getScopedOptions = (s) => {
    const containers = getContainers(s);
    for (const c of containers) {
      const raw = selectableOptions(c.querySelectorAll(OPT_SEL));
      if (!raw.length) continue;
      const vis = raw.filter(isVisible);
      if (vis.length) return {items: vis, scope: 'container'};
    }
    // A newly visible unlinked menu may be a remounted stale portal. Timing,
    // geometry, and matching text do not establish ownership, so fail closed.
    const linkedVis = [];
    for (const el of selectableOptions(document.querySelectorAll(OPT_SEL))) {
      if (!isVisible(el)) continue;
      let ownedByOtherContainer = false;
      let anc = el.parentElement;
      while (anc && anc !== document.body && anc !== document.documentElement) {
        if (anc.matches && anc.matches(CONTAINER_SEL)) {
          const ownerSels = anc.querySelectorAll('.DDLOptions__selected');
          if (ownerSels.length === 1 && ownerSels[0] !== s) {
            ownedByOtherContainer = true;
            break;
          }
        }
        anc = anc.parentElement;
      }
      if (ownedByOtherContainer) continue;
      const explicitOwner = getPortalOwner(el);
      if (explicitOwner === s) linkedVis.push(el);
    }
    if (linkedVis.length) {
      // Distinct menus independently linked to one trigger conflict: never let
      // their identical option text turn an ambiguous lookup into a click.
      const menuSel = '.DDLOptions__list, [role="listbox"]';
      // Direct references to distinct loose option nodes are distinct targets,
      // even when those nodes happen to share an unlabelled parent.
      const directIds = new Set(linkedVis.filter(el => el.id).map(el => String(el.id)));
      const directTargets = new Set();
      for (const sc of getContainers(s).concat([s])) {
        for (const attr of ['aria-controls', 'aria-owns', 'data-target', 'data-dropdown', 'data-menu', 'data-portal']) {
          String(getAttr(sc, attr) || '').split(/\s+/).forEach(tok => {
            const id = tok.replace(/^#/, '');
            if (directIds.has(id)) directTargets.add(id);
          });
        }
      }
      if (directTargets.size > 1) return {items: [], scope: 'none'};
      const groups = new Set(linkedVis.map(el =>
        (el.closest && el.closest(menuSel)) || el.parentElement || null));
      if (!groups.has(null) && !groups.has(document.body) && !groups.has(document.documentElement) && groups.size === 1)
        return {items: linkedVis, scope: 'portal-linked'};
      return {items: [], scope: 'none'};
    }
    for (const c of containers) {
      const raw = selectableOptions(c.querySelectorAll(OPT_SEL));
      if (raw.length) return {items: raw, scope: 'container-hidden'};
    }
    return {items: [], scope: 'none'};
  };
  const getSelectedText = (s) => {
    if (!s) return '';
    if (s.cloneNode) {
      const clone = s.cloneNode(true);
      if (clone.querySelectorAll) {
        clone.querySelectorAll(OPT_SEL + ', .DDLOptions__list').forEach(e => e.remove());
      }
      return ((clone.innerText || clone.textContent) || '').replace(/\s+/g, ' ').trim();
    }
    return ((s.innerText || s.textContent) || '').replace(/\s+/g, ' ').trim();
  };
  const isSelectedPlaceholder = (s) => {
    if (!s || !getSelectedText(s)) return true;
    if (hasAttr(s, 'data-placeholder') && String(getAttr(s, 'data-placeholder') || '').toLowerCase() !== 'false') return true;
    if (String(getAttr(s, 'aria-placeholder') || '') && getAttr(s, 'data-selected') === 'false') return true;
    const cls = String(s.className || '');
    if (/(?:^|[\s_-])(placeholder|unselected)(?:$|[\s_-])/i.test(cls)) return true;
    if (s.cloneNode) {
      const clone = s.cloneNode(true);
      if (clone.querySelectorAll) {
        clone.querySelectorAll(OPT_SEL + ', .DDLOptions__list').forEach(e => e.remove());
        if (clone.querySelector && clone.querySelector('[data-placeholder]:not([data-placeholder="false"]), [class*="placeholder"], [class*="unselected"]')) {
          return true;
        }
      }
    }
    return false;
  };
  const fireMouse = (el) => {
    if (!el || typeof el.dispatchEvent !== 'function') return;
    for (const type of ['mousedown', 'mouseup']) {
      try {
        const ev = typeof MouseEvent === 'function'
          ? new MouseEvent(type, {bubbles: true, cancelable: true})
          : {type: type, bubbles: true};
        el.dispatchEvent(ev);
      } catch (e) {}
    }
  };
  const closeOtherMenus = (s, forceClose) => {
    const others = getTriggers().filter(x => x !== s);
    const hasOpenOther = forceClose || others.some(o =>
      getContainers(o).some(c => selectableOptions(c.querySelectorAll(OPT_SEL)).some(isVisible))
    );
    if (!hasOpenOther) return;
    if (document.body && typeof document.body.click === 'function') {
      try { document.body.click(); } catch (e) {}
    }
    for (const o of others) {
      const stillOpen = getContainers(o).some(c => selectableOptions(c.querySelectorAll(OPT_SEL)).some(isVisible));
      if (stillOpen && typeof o.click === 'function') {
        try { o.click(); } catch (e) {}
      }
    }
  };
"""


def _open_and_read_ddl(t, idx, attempt=0, force_close=False):
    open_res = jso(t, _FITB_DOM_JS + f"""
      const s = getTrigger({idx});
      if (!s) return {{status: 'nf'}};
      closeOtherMenus(s, {'true' if force_close else 'false'});
      if (typeof s.scrollIntoView === 'function') {{
        s.scrollIntoView({{block: 'center', inline: 'nearest'}});
      }}
      const cur = getScopedOptions(s);
      if ({attempt} === 0 || {'true' if force_close else 'false'} || cur.scope === 'none' || cur.scope === 'container-hidden') {{
        if ({attempt} > 0) fireMouse(s);
        s.click();
      }}
      return {{status: 'ok', selected: getSelectedText(s), selectedPlaceholder: isSelectedPlaceholder(s)}};
    """) or {}
    if open_res.get("status") == "nf":
        return {"status": "nf", "options": [], "scope": "none", "selected": "", "selectedPlaceholder": True}
    time.sleep(0.3)
    opts_res = jso(t, _FITB_DOM_JS + f"""
      const s = getTrigger({idx});
      if (!s) return {{status: 'nf', options: [], scope: 'none', selected: '', selectedPlaceholder: true}};
      const res = getScopedOptions(s);
      return {{
        status: 'ok',
        scope: res.scope,
        selected: getSelectedText(s),
        selectedPlaceholder: isSelectedPlaceholder(s),
        options: res.items.map(getOptText)
      }};
    """) or {}
    return opts_res


def solve_fitb(t, src=""):
    """Sentence with numbered blanks, each a dropdown of options."""
    data = jso(t, _FITB_DOM_JS + r"""
      const triggers = getTriggers();
      const domCount = triggers.length;
      const comps = [...document.querySelectorAll('.learning__angPracticeW ng-component, ed-la-practicearea ng-component')];
      let text = '';
      let lists = [];
      if (comps.length && typeof ng !== 'undefined' && ng && ng.probe) {
        const qs = comps.flatMap(el => {
          const probe = ng.probe(el);
          const c = probe && probe.componentInstance;
          const q = c && c.practiceData && c.practiceData.questions;
          return q && q.length ? [...q] : [];
        });
        if (qs.length) {
          text = qs.length === 1
            ? (qs[0].text || '')
            : qs.map(q => (q && q.text) || '').filter(Boolean).join('\n');
          lists = qs.flatMap(q => ((q && q.answerLists) || []).map(l => ((l && l.answers) || []).map(a => a.txt)));
        }
      }
      if (!lists.length && !domCount) return null;
      const domLists = triggers.map(s => {
        for (const c of getContainers(s)) {
          const opts = selectableOptions(c.querySelectorAll(OPT_SEL)).map(getOptText);
          if (opts.length) return opts;
        }
        return [];
      });
      let domText = '';
      if (!text || domCount > lists.length) {
        const area = document.querySelector('.learning__angPracticeW, ed-la-practicearea, #pmContainer');
        if (area && area.cloneNode) {
          const clone = area.cloneNode(true);
          if (clone.querySelectorAll) {
            clone.querySelectorAll(OPT_SEL + ', .DDLOptions__list').forEach(e => e.remove());
            [...clone.querySelectorAll('.DDLOptions__selected')].forEach((el, idx) => {
              el.textContent = ' [[' + (idx + 1) + ']] ';
            });
          }
          domText = ((clone.innerText || clone.textContent) || '').replace(/\s+/g, ' ').trim().slice(0, 2500);
        }
      }
      return {text: text || domText, domText: domText, lists: lists, domCount: domCount, domLists: domLists};
    """)
    if not data:
        return "other: fitb: nodata"
    pd_lists = list(data.get("lists") or [])
    dom_count = data.get("domCount")
    if not isinstance(dom_count, int):
        cnt = jso(t, _FITB_DOM_JS + "return getTriggers().length;")
        dom_count = cnt if isinstance(cnt, int) else len(pd_lists)
    dom_lists = list(data.get("domLists") or [])
    total_blanks = max(len(pd_lists), dom_count)
    if total_blanks == 0:
        return "other: fitb: nodata"

    all_lists = []
    has_pd = []
    for k in range(total_blanks):
        if k < len(pd_lists):
            all_lists.append(list(pd_lists[k] or []))
            has_pd.append(True)
        else:
            extra = list(dom_lists[k]) if k < len(dom_lists) and dom_lists[k] else []
            if not extra:
                probed = _open_and_read_ddl(t, k, attempt=0, force_close=True)
                extra = list(probed.get("options") or [])
            all_lists.append(extra)
            has_pd.append(False)

    prompt_text = (
        data.get("domText")
        if (dom_count > len(pd_lists) and data.get("domText"))
        else (data.get("text") or data.get("domText") or "")
    )
    lines = "\n".join(f"{i+1}. {' | '.join(opts)}" for i, opts in enumerate(all_lists))
    ctx = f"SOURCE MATERIAL:\n{src}\n\n" if src and str(src).strip() else ""
    prompt = (ctx + "Sentence with blanks (numbered):\n" + prompt_text +
              "\n\nOptions per blank:\n" + lines +
              '\n\nPick the best option for each blank. Reply ONLY JSON:'
              ' {"1": "<exact option text>", "2": "..."}')
    picks = ask_json(prompt, max_tokens=600) or {}
    out = []
    verified_targets = {}
    for i, opts in enumerate(all_lists):
        want = picks.get(str(i + 1)) or picks.get(i + 1) or ""
        if not str(want).strip():
            out.append(f"{i}=?")
            continue
        locked_target = None
        if has_pd[i]:
            if not opts:
                out.append(f"{i}=noopt")
                continue
            exp_idx = _match_ddl_option(want, opts)
            if exp_idx is None:
                out.append(f"{i}=noopt")
                continue
            locked_target = opts[exp_idx]
        elif opts:
            exp_idx = _match_ddl_option(want, opts)
            if exp_idx is not None:
                locked_target = opts[exp_idx]

        st = "noopt"
        force_close = False
        for attempt in range(3):
            opts_res = _open_and_read_ddl(t, i, attempt=attempt, force_close=force_close)
            force_close = False
            if opts_res.get("status") == "nf":
                st = "nf"
                break
            dom_opts = opts_res.get("options") or []
            scope = opts_res.get("scope") or "none"
            if scope in ("document", "portal-linked") and opts:
                exp_norms = {_norm_ddl(o, strip_punct=True) for o in opts if _norm_ddl(o, strip_punct=True)}
                dom_norms = {_norm_ddl(o, strip_punct=True) for o in dom_opts if _norm_ddl(o, strip_punct=True)}
                if exp_norms and dom_norms != exp_norms:
                    force_close = True
                    st = "noopt"
                    continue
            if locked_target is not None:
                match_idx = _match_ddl_exact(locked_target, dom_opts)
            else:
                match_idx = _match_ddl_option(want, dom_opts)
                if match_idx is not None:
                    locked_target = dom_opts[match_idx]
            if match_idx is None:
                force_close = True
                st = "noopt"
                continue
            chosen_text = dom_opts[match_idx]
            pick_res = jso(t, _FITB_DOM_JS + f"""
              const s = getTrigger({i});
              if (!s) return {{clicked: 0, selected: '', selectedPlaceholder: true}};
              const allTrigs = getTriggers();
              const otherBefore = allTrigs.map(tEl => tEl === s ? null : getSelectedText(tEl));
              const selBefore = getSelectedText(s);
              const selPhBefore = isSelectedPlaceholder(s);
              const res = getScopedOptions(s);
              const wantText = {json.dumps(chosen_text)};
              const candidate = res.items[{match_idx}];
              const pick = (candidate && getOptText(candidate) === wantText)
                ? candidate
                : (res.items.find(el => getOptText(el) === wantText) || null);
              if (!pick) return {{clicked: 0, selected: selBefore, selectedPlaceholder: selPhBefore}};
              if (typeof pick.scrollIntoView === 'function') {{
                pick.scrollIntoView({{block: 'nearest', inline: 'nearest'}});
              }}
              if ({attempt} > 0) fireMouse(pick);
              pick.click();
              let selAfter = getSelectedText(s);
              let selPh = isSelectedPlaceholder(s);
              if ({attempt} > 0 && (selPh || selAfter !== wantText) && pick.querySelector) {{
                const child = pick.querySelector('a, span, div, button');
                if (child && typeof child.click === 'function') {{
                  fireMouse(child);
                  child.click();
                  selAfter = getSelectedText(s);
                  selPh = isSelectedPlaceholder(s);
                }}
              }}
              const otherMutated = allTrigs.some((tEl, k) => tEl !== s && getSelectedText(tEl) !== otherBefore[k]);
              if (otherMutated) {{
                return {{clicked: 0, otherMutated: 1, selected: selAfter, selectedPlaceholder: selPh}};
              }}
              let rect = null;
              if (isVisible(pick) && getOptText(pick) === wantText && pick.getBoundingClientRect) {{
                const r = pick.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {{
                  rect = {{cx: Math.round(r.x + r.width / 2), cy: Math.round(r.y + r.height / 2), w: r.width, h: r.height}};
                }}
              }}
              return {{
                clicked: 1,
                scope: res.scope,
                wasPreSelected: (!selPhBefore && selBefore === selAfter),
                closedOnPick: !isVisible(pick),
                selected: selAfter,
                selectedPlaceholder: selPh,
                rect: rect
              }};
            """) or {}
            time.sleep(0.25)
            if not pick_res.get("clicked"):
                force_close = True
                st = "noopt"
                continue
            sel_after = pick_res.get("selected") or ""
            sel_ph = bool(pick_res.get("selectedPlaceholder"))
            if pick_res.get("scope") == "document" and pick_res.get("wasPreSelected") and not pick_res.get("closedOnPick"):
                still_open = jso(t, _FITB_DOM_JS + f"const s = getTrigger({i}); return getScopedOptions(s).scope === 'document' ? 1 : 0;")
                if still_open:
                    force_close = True
                    st = "noopt"
                    continue
            if not _ddl_selected_ok(sel_after, locked_target, sel_ph):
                chk = jso(
                    t,
                    _FITB_DOM_JS
                    + f"const s = getTrigger({i}); return {{selected: getSelectedText(s), selectedPlaceholder: isSelectedPlaceholder(s)}};",
                ) or {}
                sel_after = chk.get("selected") or ""
                sel_ph = bool(chk.get("selectedPlaceholder"))
            if not _ddl_selected_ok(sel_after, locked_target, sel_ph) and attempt > 0:
                rect = pick_res.get("rect")
                if isinstance(rect, dict) and rect.get("w", 0) > 0 and callable(getattr(t, "click_xy", None)):
                    t.click_xy(rect["cx"], rect["cy"])
                    time.sleep(0.2)
                    chk = jso(
                        t,
                        _FITB_DOM_JS
                        + f"const s = getTrigger({i}); return {{selected: getSelectedText(s), selectedPlaceholder: isSelectedPlaceholder(s)}};",
                    ) or {}
                    sel_after = chk.get("selected") or ""
                    sel_ph = bool(chk.get("selectedPlaceholder"))
            if _ddl_selected_ok(sel_after, locked_target, sel_ph):
                verified_targets[i] = locked_target
                st = "ok"
                break
            st = "empty"
        out.append(f"{i}={st}")

    audit = jso(t, _FITB_DOM_JS + """
      return getTriggers().map(s => ({
        selected: getSelectedText(s),
        selectedPlaceholder: isSelectedPlaceholder(s)
      }));
    """)
    if isinstance(audit, list):
        for j, state_j in enumerate(audit):
            sel_j = (state_j or {}).get("selected") or ""
            ph_j = bool((state_j or {}).get("selectedPlaceholder", True))
            if j >= len(out):
                out.append(f"{j}=empty")
            elif out[j].endswith("=ok"):
                if not _ddl_selected_ok(sel_j, verified_targets.get(j, ""), ph_j):
                    out[j] = f"{j}=empty"
        for j in range(len(audit), len(out)):
            if out[j].endswith("=ok"):
                out[j] = f"{j}=nf"

    summary = "fitb: " + " ".join(out)
    if not out or any(not item.endswith("=ok") for item in out):
        return "other: " + summary
    return summary


def solve_select_text(t, src):
    prompt = t.js("(() => (document.querySelector('.learning__taskInstruction, .prSelectText__instruction, .learning__tasksNav_instructionsW')?.innerText || document.body.innerText.slice(0, 500)))()")
    spans = t.js("(() => [...document.querySelectorAll('.learning__selectTxt_st, span.st')].map((e, idx) => ({idx: idx, text: e.innerText.trim()})))()")
    if not spans:
        return "select_text: no spans"
    q = (f"SOURCE MATERIAL:\n{src}\n\nINSTRUCTION:\n{prompt}\n\nCANDIDATE SENTENCES:\n" +
         "\n".join(f"{s['idx']}. {s['text']}" for s in spans) +
         '\n\nPick the 0-based index of the sentence that matches the instruction. Reply {"index": <int>}.')
    r = ask_json(q, max_tokens=100) or {}
    idx = r.get("index", 0)
    if not isinstance(idx, int) or idx < 0 or idx >= len(spans):
        idx = 0
    t.js(f"""(() => {{
      const els = document.querySelectorAll('.learning__selectTxt_st, span.st');
      if(els[{idx}]) {{
        els[{idx}].click();
        els[{idx}].classList.add('selected');
      }}
      return 1;
    }})()""")
    return f"select_text: picked {idx} ({spans[idx]['text'][:30]})"


def do_task(t, src):
    # A test question renders a beat after the counter updates; classifying too
    # early returns 'other', and the caller then advances to the next question
    # with this one unanswered (scores ~0% and the submit dialog complains).
    for _ in range(40):
        ready = t.js("""(() => (document.querySelector('.prMCQ__qaSet')
          || document.querySelector('.prOpenEnded__qaItemText')
          || document.querySelector('.writingEditFrame .writingEditPracticeWrapper input[type=text]')
          || document.querySelector('.writingEditFrame .writingEditPracticeWrapper textarea')
          || document.querySelector('.DDLOptions__selected')
          || document.querySelector('.lessonMultipleAnswer')
          || document.querySelector('.dnditem')
          || document.querySelector('.sequenceZone')
          || document.querySelector('.prSeq__zone--txt')
          || document.querySelector('.TTpanswerDiv')
          || document.querySelector('.learning__selectTxt_st, span.st')
          || (window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized))
          ? 1 : 0)()""")
        if ready:
            break
        time.sleep(0.25)
    kind = t.js("""(() => {
      if(window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized && document.querySelector('.mce-edit-area, iframe[id$=_ifr]')) return 'writing';
      if(document.querySelector('.prOpenEnded__qaItemText')) return 'open';
      if(document.querySelector('.writingEditFrame .writingEditPracticeWrapper input[type=text], .writingEditFrame .writingEditPracticeWrapper textarea')) return 'errorfix';
      if(document.querySelector('.DDLOptions__selected')) return 'fitb';
      if(document.querySelectorAll('.prMCQ__qaSet').length) return 'mcq';
      if(document.querySelectorAll('.lessonMultipleAnswer').length) return 'multi';
      if(document.querySelector('.sequenceZone, .prSeq__zone--txt, .prSeqImg__zone, .sequenceZoneWrapper')) return 'sequence';
      if(document.querySelectorAll('.dnditem').length && document.querySelectorAll('.dndZone').length) {
        if(!document.querySelector('.dndZone[dg_name="TTpTablePlaceHolder"], .dndZone#TTpTablePlaceHolder')) return 'sequence';
        return 'drag';
      }
      if(document.querySelectorAll('.TTpanswerDiv').length && document.querySelectorAll('.draggable').length) return 'lcloze';
      if(document.querySelectorAll('.draggable.wordBankTile').length && document.querySelectorAll('.dndZone').length) return 'cloze';
      if(document.querySelectorAll('.learning__selectTxt_st, span.st').length) return 'select_text';
      return 'other';
    })()""")
    if kind == "mcq":
        return solve_mcq(t, src)
    if kind == "multi":
        return solve_multi(t, src)
    if kind == "sequence":
        return solve_sequence(t, src)
    if kind == "drag":
        return solve_drag(t, src)
    if kind == "cloze":
        return solve_cloze(t, src)
    if kind == "lcloze":
        return solve_cloze_legacy(t, src)
    if kind == "fitb":
        return solve_fitb(t, src)
    if kind == "open":
        return solve_openended(t, src)
    if kind == "errorfix":
        return solve_errorfix(t, src)
    if kind == "select_text":
        return solve_select_text(t, src)
    if kind == "writing":
        return solve_writing(t, src, task_text(t))
    return "other: " + (task_text(t)[:60].replace("\n", " "))


def next_task(t):
    return jso(t, "const n=document.querySelector('.learning__taskNext'); if(n){n.click(); return 1;} return 0;")


def set_step(t, index):
    """Switch step via navigationService or ed-la-dropdownlist component (index 0-based)."""
    return t.js(f"""(() => {{
      const app = document.querySelector('app') ? window.ng?.probe?.(document.querySelector('app'))?.componentInstance : null;
      const nav = app?.navigationService;
      if (nav && nav._stepsList && nav._stepsList.Children && nav._stepsList.Children[{index}]) {{
        const k = nav._stepsList.Children[{index}];
        k.IsLocked = false;
        try {{
          nav.selectedChanged({{
            nodeId: k.NodeId,
            courseNodeType: 4,
            selectedIndex: {index}
          }}, true, false);
          return k.Name + ' (' + k.NodeId + ')';
        }} catch(e) {{}}
      }}
      const dd1 = document.querySelectorAll('ed-la-dropdownlist')[1];
      const comp = dd1 ? window.ng?.probe?.(dd1)?.componentInstance : null;
      const listObj = comp?.dropDownListObj;
      if (comp && listObj && listObj.Children && listObj.Children[{index}]) {{
        const target = listObj.Children[{index}];
        target.IsLocked = false;
        try {{
          comp.selectListItem({{preventDefault(){{}}}}, target.NodeId, false, {index} + 1);
          return target.Name + ' (' + target.NodeId + ') via comp';
        }} catch(e) {{}}
      }}
      return 'no step ' + {index};
    }})()""")


def set_next_step(t):
    """Advance to the next step via ed-la-dropdownlist component or navigationService."""
    return t.js("""(() => {
      const dd1 = document.querySelectorAll('ed-la-dropdownlist')[1];
      const comp = dd1 ? window.ng?.probe?.(dd1)?.componentInstance : null;
      const listObj = comp?.dropDownListObj;
      const app = document.querySelector('app') ? window.ng?.probe?.(document.querySelector('app'))?.componentInstance : null;
      const nav = app?.navigationService;
      
      let cur = -1;
      if (nav && nav._stepsList && typeof nav._stepsList.SelectedIndex === 'number') {
        cur = nav._stepsList.SelectedIndex;
      }
      if (cur < 0 && listObj && typeof listObj.SelectedIndex === 'number') {
        cur = listObj.SelectedIndex;
      }
      if (cur < 0 && comp && typeof comp.selectedListItemIndex === 'number') {
        cur = comp.selectedListItemIndex;
      }
      
      const totalSteps = (listObj && listObj.Children ? listObj.Children.length : 0) || (nav && nav._stepsList && nav._stepsList.Children ? nav._stepsList.Children.length : 0);
      
      if (cur < 0) cur = 0;
      if (totalSteps > 0 && cur + 1 >= totalSteps) return 'last step';
      
      const nextIdx = cur + 1;
      if (nav && nav._stepsList && nav._stepsList.Children && nav._stepsList.Children[nextIdx]) {
        const k = nav._stepsList.Children[nextIdx];
        k.IsLocked = false;
        try {
          nav.selectedChanged({
            nodeId: k.NodeId,
            courseNodeType: 4,
            selectedIndex: nextIdx
          }, true, false);
          return (k.Name || 'step') + ' (' + k.NodeId + ')';
        } catch(e) {}
      }
      
      if (comp && listObj && listObj.Children && listObj.Children[nextIdx]) {
        const target = listObj.Children[nextIdx];
        target.IsLocked = false;
        try {
          comp.selectListItem({preventDefault(){}}, target.NodeId, false, nextIdx + 1);
          return (target.Name || 'step') + ' (' + target.NodeId + ') via comp';
        } catch(e) {}
      }

      // Fallback DOM clicks
      const arrow = document.querySelector('.arrow-right, .nextStepArrow, a.learning__stepNext, .learning__nextItemLink, .learning__taskNext');
      if (arrow) {
        arrow.click();
        return 'via arrow click';
      }
      return 'cannot advance step';
    })()""")


def start_test(t):
    return jso(t, "const a=document.querySelector('.btnStartTest'); if(a){a.click(); return 1;} return 0;")


def submit_test(t):
    return jso(t, "const a=document.querySelector('.learning__submitTestLink'); if(a){a.click(); return 1;} return 0;")


def main(max_tasks=200):
    t = edlib.tab()
    last_lesson = None
    lesson_resource = ""
    transcript_state = {}
    src = ""
    stuck = 0
    prev_sig = None
    for i in range(max_tasks):
        st = state(t)
        if "login" in st["url"]:
            print("LOGIN LOST")
            return
        sig = (st["lesson"], st["step"], st["counter"])
        if sig == prev_sig:
            stuck += 1
        else:
            stuck = 0
        prev_sig = sig

        if st["lesson"] != last_lesson:
            last_lesson = st["lesson"]
            s = source_text(t) or {}
            lesson_resource = s.get("resource") or ""
            transcript_state = {}
            src = lesson_resource + "\n" + (s.get("body") or "")
            print(f"== {st['lesson']} / {st['step']}")

        # step intro / test entry screens
        if st["step"].startswith("Step 3") and st["counter"] is None:
            if start_test(t):
                print("test started")
                time.sleep(6)
                prev_sig = None
                continue

        if st["counter"] is None and "Start Test" not in t.js("(() => document.body.innerText)()"):
            # no task loaded (intro/reading screen): play media if any, then Next
            played = play_media(t)
            next_task(t)
            time.sleep(3)
            print(f"-- passthrough (media={'y' if played else 'n'})")
            prev_sig = None
            continue

        # test finished? submit button present on last question
        sub = jso(t, "return document.querySelector('.learning__submitTestLink')?1:0;")
        total = st["total"]
        if sub and total and st["counter"] == total and st["step"].startswith("Step 3"):
            submit_test(t)
            time.sleep(4)
            body = t.js("(() => document.body.innerText.slice(0,400))()")
            m = [ln for ln in body.split("\n") if "test score" in ln.lower() or "%" in ln]
            print("TEST SUBMITTED", m[:2])
            prev_sig = None
            continue

        # audio/video comprehension task: refresh per-task source and attach transcript
        cur = source_text(t) or {}
        res_txt = (cur.get("resource") or "").strip() or lesson_resource
        base_src = res_txt + "\n" + (cur.get("body") or "")
        task_src = resolve_task_transcript(
            t, base_src, (st.get("lesson"), st.get("step")), transcript_state
        )

        if stuck >= 3:
            # try switching step, then give up
            print("STUCK at", sig)
            return

        neutralize(t)
        out = do_task(t, task_src)
        print(f"[{st['counter']}/{st['total']}] {out[:110]}")
        next_task(t)
        time.sleep(2.5)
        neutralize(t)


DUMP_TASK_JS = """(() => {
  const practiceArea = document.querySelector('ed-la-practicearea') || document.querySelector('#pmContainer') || document.body;
  let practiceData = null;
  let compState = null;
  try {
    const probe = window.ng?.probe?.(document.querySelector('ed-la-practicearea'));
    const comp = probe?.componentInstance;
    if (comp) {
      practiceData = comp.practiceData || comp.itemInfo || null;
      compState = {};
      const keys = ['doneProgress', 'isSubmitted', 'currentState', 'taskType', 'questionType', 'mode', 'status', 'step', 'counter'];
      for (const k of keys) {
        if (k in comp) {
          try { compState[k] = comp[k]; } catch(e){}
        }
      }
    }
  } catch(e) {}

  const interactives = [];
  try {
    const sel = 'button, a, [role="button"], .button, input[type="button"], input[type="submit"], .openSpeech__btn, .panelButton, .arrow-right, .nextStepArrow';
    document.querySelectorAll(sel).forEach(el => {
      const rect = el.getBoundingClientRect();
      const visible = (el.offsetParent !== null || rect.width > 0) && window.getComputedStyle(el).display !== 'none';
      if (visible) {
        interactives.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || '').toString().trim(),
          id: el.id || '',
          text: (el.innerText || el.textContent || '').trim().slice(0, 80),
          rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) }
        });
      }
    });
  } catch(e) {}

  return {
    html: practiceArea ? practiceArea.innerHTML : '',
    practiceData: practiceData,
    compState: compState,
    interactives: interactives,
    body: (document.body?.innerText || '').trim(),
    url: window.location.href
  };
})()"""


def dump_task(t, out_path: str, meta: dict | None = None) -> str:
    """Dump current task DOM, interactive elements, angular metadata, and screenshot for offline debugging."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        raw = t.js(DUMP_TASK_JS) or {}

        # Capture screenshot if tab driver supports CDP
        screenshot_b64 = None
        try:
            res = t.cdp("Page.captureScreenshot", format="png", quality=80)
            screenshot_b64 = res.get("data") if isinstance(res, dict) else None
        except Exception:
            pass

        payload = {
            "meta": meta or {},
            "html": raw.get("html", ""),
            "practiceData": raw.get("practiceData"),
            "compState": raw.get("compState"),
            "interactives": raw.get("interactives") or [],
            "body": raw.get("body", ""),
            "url": raw.get("url", ""),
            "screenshot": screenshot_b64,
            "timestamp": time.time()
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return out_path
    except Exception as e:
        return f"dump-err: {e}"


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
