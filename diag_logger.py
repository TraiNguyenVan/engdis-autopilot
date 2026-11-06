import json
import time
from pathlib import Path

class DiagnosticLogger:
    def __init__(self, log_dir="logs_diag", max_evidence=50):
        self.log_dir = Path(log_dir)
        self.evidence_dir = self.log_dir / "evidence"
        self.events_file = self.log_dir / "events.jsonl"
        self.max_evidence = max_evidence
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def log_task(self, unit, lesson, step, task, kind, attempt, duration_s, result, advanced, details=None):
        event = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "unit": unit,
            "lesson": lesson,
            "step": step,
            "task": task,
            "type": kind,
            "attempt": attempt,
            "duration_s": round(duration_s, 2),
            "result": result,
            "advanced": advanced,
            "details": details or {}
        }
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event

    def save_failure_evidence(self, task_sig, dom_snippet=None, screenshot_bytes=None, error_msg=None):
        ts = int(time.time())
        clean_sig = "".join(c if c.isalnum() else "_" for c in str(task_sig))
        evidence_prefix = f"{ts}_{clean_sig}"
        saved = {}

        if error_msg or dom_snippet:
            meta_path = self.evidence_dir / f"{evidence_prefix}.json"
            meta = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "task": task_sig,
                "error": error_msg,
                "dom_snippet": (dom_snippet[:2000] if dom_snippet else None)
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            saved["meta"] = str(meta_path)

        if screenshot_bytes:
            img_path = self.evidence_dir / f"{evidence_prefix}.png"
            with open(img_path, "wb") as f:
                f.write(screenshot_bytes)
            saved["screenshot"] = str(img_path)

        return saved
