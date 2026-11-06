"""Non-interactive login for ed22.engdis.com.

Credentials come from the environment (ED_USER / ED_PASS) or from a 0600 file
(ED_CRED, default /opt/data/.config/engdis/cred, two lines: username, password).
Never printed. Never written to git.

The login form has decoy password inputs (aganistAutoComplete, foilautofill) that
swallow autofill; they are stripped before typing into the real field.

Usage:
    python3 login.py            # login if needed, print result
    python3 login.py --force    # always submit the form
"""
import os
import sys
import time

import edlib
import config

LOGIN_URL = "https://ed22.engdis.com/ptithcm#/login"
HOME_URL = "https://ed22.engdis.com/ptithcm#/home"
CRED = config.CRED_PATH

_DECOY_JS = """(() => {
  document.querySelectorAll('input[name=aganistAutoComplete],input[name=foilautofill]')
    .forEach(e => { e.removeAttribute('name'); e.style.display = 'none'; });
  return 1;
})()"""

_LOGGED_JS = """(() => {
  if (location.href.indexOf('#/login') >= 0) return 0;
  const b = document.body ? (document.body.innerText || '') : '';
  if (/Member Login/.test(b) && !/Hello /.test(b)) return 0;
  if (/Hello /.test(b) || document.querySelector('.home__unitW')) return 1;
  // learning area is only reachable with a live session: do NOT navigate away
  // from it (navigating to #/home loses the open lesson)
  if (document.querySelector('ed-la-dropdownlist')) return 1;
  if (location.href.indexOf('learningArea') >= 0 && b.length > 200) return 1;
  // #/home still rendering: session is alive (a dead session bounces to #/login)
  if (location.href.indexOf('#/home') >= 0 && b.length > 120) return 1;
  return 0;
})()"""


def creds():
    """Return (user, password) or (None, None). Values are never logged."""
    u, p = os.environ.get("ED_USER"), os.environ.get("ED_PASS")
    if u and p:
        return u, p
    if not CRED or not os.path.isfile(CRED):
        return None, None
    try:
        st = os.stat(CRED)
        if st.st_mode & 0o077:
            print("login: warning — %s is readable by group/other; chmod 600" % CRED)
        lines = [x.strip() for x in open(CRED, encoding="utf-8").read().splitlines() if x.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    except OSError as e:
        print("login: cannot read %s: %s" % (CRED, e))
    return None, None


def logged_in(t):
    try:
        return bool(t.js(_LOGGED_JS))
    except Exception:
        return False


def _type(t, selector, text):
    ok = t.js("(() => {const e=document.querySelector(%s); if(!e) return 0;"
              " e.value=''; e.focus(); return 1;})()" % _q(selector))
    if not ok:
        return False
    t.send("Input.insertText", text=text)
    t.js("""(() => {const e=document.querySelector(%s); if(!e) return 0;
      e.dispatchEvent(new Event('input',{bubbles:true}));
      e.dispatchEvent(new Event('change',{bubbles:true}));
      e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'x'}));
      return 1;})()""" % _q(selector))
    return True


def _q(s):
    import json
    return json.dumps(s)


def _accept_dialog(t):
    """'You are already logged in' dialog offers input.okButton."""
    return t.js("""(() => {
      const f = document.querySelector('iframe#colorBoxIframe');
      const d = f ? f.contentDocument : document;
      const b = [...(d||document).querySelectorAll('input[type=button],input[type=submit],button,a')]
        .filter(e => /log ?in on this device|^(ok|continue|yes)$/i.test(((e.value||e.innerText||'')+'').trim()));
      if (!b.length) return 0;
      b[b.length-1].click();
      return 1;
    })()""")


def login(t, force=False):
    """Log in. Returns True on success."""
    u, p = creds()
    if not u or not p:
        print("login: CREDS-MISSING — write two lines to %s (chmod 600) "
              "or set ED_USER/ED_PASS" % CRED)
        return False

    if not force and logged_in(t):
        print("login: already in")
        return True

    t.goto(LOGIN_URL, wait=5)
    for _ in range(10):
        if t.js("!!document.querySelector('input[name=password]')"):
            break
        time.sleep(1)
    else:
        # No form means the SPA is still authenticated and bounced us home;
        # that is success, not a login failure.
        if logged_in(t):
            print("login: ok (no form — session already live)")
            return True
        print("login: no form on page (%s)" % t.js("location.href"))
        return False

    t.js(_DECOY_JS)
    if not _type(t, "input[name=userName]", u):
        print("login: username field missing")
        return False
    if not _type(t, "input[name=password]", p):
        print("login: password field missing")
        return False

    t.js("(() => {const b=document.querySelector('#submit1'); if(b) b.click(); return 1;})()")

    end = time.time() + 25
    while time.time() < end:
        if logged_in(t):
            print("login: ok")
            return True
        if _accept_dialog(t):
            time.sleep(3)
            if logged_in(t):
                print("login: ok (accepted already-logged-in dialog)")
                return True
        time.sleep(1)

    # Sometimes Auth succeeds and writes the Student cookie but the SPA stays on
    # the login view; one direct navigation settles it.
    t.goto(HOME_URL, wait=6)
    if logged_in(t):
        print("login: ok (needed an explicit #/home navigation)")
        return True

    body = t.js("(() => (document.body.innerText||'').slice(0,200))()")
    print("login: FAILED — %s" % str(body).replace("\n", " | ")[:180])
    return False


def ensure_login(t):
    """Cheap check, then login only if needed. Safe to call every lesson."""
    if logged_in(t):
        return True
    return login(t)


if __name__ == "__main__":
    tab = edlib.tab()
    sys.exit(0 if login(tab, force="--force" in sys.argv) else 2)
