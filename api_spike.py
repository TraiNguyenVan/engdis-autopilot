"""Track B spike: talk to the English Discoveries REST API from page context.

Auth = Bearer token in localStorage('Student').Token. API host from localStorage('api').

Commands:
  tree                  dump the course tree (NodeId/Name/Progress/CourseNodeType)
  read <ParticleId>     POST CourseTree/GetUserNodeProgress for one node
  write <ItemId>        ONE Progress/SetProgressPerTask call, refused unless the
                        owning lesson is already >=99.9% (so it can only confirm
                        the path, never grant new credit)
  replay <LessonName>   list the task NodeIds of a lesson (dry run, no writes)
"""
import json
import sys

import edlib

COURSE_ID = 45689

TOKEN_JS = r"""
(() => {
  try {
    const ls = JSON.parse(localStorage.getItem('Student') || 'null');
    const api = JSON.parse(localStorage.getItem('api') || 'null');
    return {tok: ls && (ls.Token || ls.token), host: api && api.host};
  } catch (e) { return {err: String(e)}; }
})()
"""


def client(t):
    info = t.js(TOKEN_JS) or {}
    if not info.get("tok"):
        raise SystemExit("no token in localStorage('Student')")
    return info["tok"], (info.get("host") or "https://edwebservices2.engdis.com/").rstrip("/") + "/api/"


def call(t, tok, url, body):
    js = (
        "(async () => {"
        " const r = await fetch(%s, {method: 'POST', headers: {'Content-Type': 'application/json',"
        " 'Authorization': %s}, body: %s});"
        " const x = await r.text();"
        " return {status: r.status, len: x.length, body: x.slice(0, 300)};"
        "})()" % (json.dumps(url), json.dumps("Bearer " + tok), json.dumps(json.dumps(body)))
    )
    return t.js(js)


def tree(t, tok, base):
    r = call(t, tok, base + "CourseTree/GetUserNodeProgress/%d" % COURSE_ID,
             [{"ParticleId": COURSE_ID, "NodeType": 1, "LockedNodes": None,
               "particleHasProgress": True, "lowestNodeType": 6}])
    if r.get("status") != 200:
        raise SystemExit("tree failed: %s" % r)
    # full body is bigger than the truncated preview: refetch untruncated
    js = (
        "(async () => {"
        " const r = await fetch(%s, {method: 'POST', headers: {'Content-Type': 'application/json',"
        " 'Authorization': %s}, body: %s});"
        " return await r.json();"
        "})()" % (
            json.dumps(base + "CourseTree/GetUserNodeProgress/%d" % COURSE_ID),
            json.dumps("Bearer " + tok),
            json.dumps(json.dumps([{"ParticleId": COURSE_ID, "NodeType": 1, "LockedNodes": None,
                                    "particleHasProgress": True, "lowestNodeType": 6}])))
    )
    return t.js(js)


def walk(node, depth=0):
    yield depth, node
    for c in node.get("Children") or []:
        yield from walk(c, depth + 1)


def main(argv):
    t = edlib.tab()
    tok, base = client(t)
    cmd = argv[0] if argv else "tree"
    data = tree(t, tok, base)
    root = data[0] if isinstance(data, list) else data

    if cmd == "tree":
        for d, n in walk(root):
            print("%s%d %s %s %.1f%%" % ("  " * d, n.get("CourseNodeType"), n.get("NodeId"),
                                         (n.get("Name") or "")[:40], 100 * (n.get("Progress") or 0)))
        return 0

    if cmd == "read":
        pid = int(argv[1])
        print(json.dumps(call(t, tok, base + "CourseTree/GetUserNodeProgress/%d" % pid,
                              [{"ParticleId": pid, "NodeType": 1, "LockedNodes": None,
                                "particleHasProgress": True, "lowestNodeType": 6}]), indent=1))
        return 0

    if cmd == "write":
        item = int(argv[1])
        owner, progress = None, None
        for _, n in walk(root):
            for c in n.get("Children") or []:
                if c.get("NodeId") == item:
                    owner, progress = n, (n.get("Progress") or 0)
        print("item %d owner=%s progress=%.3f" % (item, (owner or {}).get("Name"), progress or 0))
        if progress is None or progress < 0.999:
            print("REFUSED: owner lesson not complete — this would grant unearned credit")
            return 2
        r = call(t, tok, base + "Progress/SetProgressPerTask", {"CourseId": COURSE_ID, "ItemId": item})
        print(json.dumps(r, indent=1))
        return 0

    if cmd == "replay":
        name = argv[1].lower()
        for _, n in walk(root):
            if name in (n.get("Name") or "").lower() and n.get("Children"):
                print("## %s %.1f%%" % (n.get("Name"), 100 * (n.get("Progress") or 0)))
                for c in n["Children"]:
                    print("  task", c.get("NodeId"), (c.get("Name") or "")[:50],
                          "done" if c.get("IsDone") else "-")
        return 0

    print("unknown command")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
