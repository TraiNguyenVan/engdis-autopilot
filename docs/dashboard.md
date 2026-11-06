# Read-only progress dashboard

Run `python3 dashboard_server.py --port 8765` from this repository, then visit http://127.0.0.1:8765/ on the same machine. Stop with Ctrl-C. Python 3 and Linux `/proc` are required for process status. No extra packages are needed.

The dashboard reads saved `cover_report_u*.json` reports (newest valid, falling back to `cover_report.json`), log file timestamps and a bounded tail for an activity category, and process names/PIDs from `/proc`. Raw log lines are not exposed. Reports are saved snapshots and may be stale; an absent score is Unknown, not zero. Process presence does not prove healthy operation or progress. Missing reports or logs appear as Unknown; file errors appear on the page.

The dashboard never starts or navigates Engdis, contacts CDP, or controls the harness. It has no authentication and binds only to loopback. **Do not expose it publicly or through a tunnel without independently enforced authentication and access control.** Progress and lesson names are private data.
