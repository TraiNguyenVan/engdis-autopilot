# Safety, Ethics, and Responsible Use Policy

## Purpose & Scope
`engdis-autopilot` is an automated browser testing and accessibility research harness designed to demonstrate headless Chrome DevTools Protocol (CDP) instrumentation, structured logging, and multimodal LLM integration with dynamic web applications.

This software is intended strictly for:
- Automated QA and regression testing of courseware interfaces.
- Browser automation and CDP instrumentation research.
- Evaluation of LLM solving accuracy on multi-modal web exercises in controlled environments.

## Academic Integrity & Terms of Service Notice
Users are responsible for ensuring that their use of this software complies with:
1. Applicable institutional honor codes, university academic integrity policies, and examination regulations.
2. The Terms of Service (ToS) and Acceptable Use Policies of any web platform accessed.

**Do not use this software to misrepresent coursework completion, bypass academic evaluations dishonestly, or gain unearned educational credentials.**

## Operational Safety Safeguards

### 1. Dry Run Mode
Always verify task discovery and navigation logic before enabling mutation or submission:
```bash
export ED_DRY_RUN=1
python3 auto.py
```
When `ED_DRY_RUN=1`, the harness traverses exercises and runs solvers without clicking final test submissions or mutating persistent completion states.

### 2. Rate Limiting and Server Etiquette
- Do not execute high-frequency concurrent automation loops against shared infrastructure.
- Respect network timeouts and server load limits.
- Built-in delays and retry intervals prevent accidental denial-of-service conditions against target servers.

### 3. Emergency Stop Controls
To instantly halt execution across loops and background processes:
```bash
touch STOP
```
Active runner loops check for the existence of `STOP` at every stage boundary and terminate immediately upon detection.

## Credential & Data Privacy Safeguards
- **Never commit credentials**: Keep student credentials (`cred`), session tokens, cookies (`cookies*.json`), and `.env` files outside git tracking.
- All credential files are pre-configured in `.gitignore`.
- Exercise transcripts and diagnostic logs may contain personal progress data; keep them protected in local environments.

## Disclaimer of Liability
This software is provided "as is", without warranty of any kind. Authors and contributors are not liable for any account suspension, institutional disciplinary action, or damages resulting from the use or misuse of this codebase.
