"""
obs.py — one place all scripts log through, so every run and every Claude call is
traceable when something breaks.

Two append-only JSONL files under data/logs/ (also echoed concisely to stdout so
the cron logs keep a human-readable trail):
  runs.jsonl    one record per script run (start/end/error + traceback + duration)
  claude.jsonl  one record per `claude -p` call (label, prompt, raw output, parsed
                JSON, Claude's own `rationale`, duration, errors)

Usage:
    import obs
    with obs.run("reply_agent"):
        ...
    raw, parsed = obs.claude(CMD, prompt, label="reply:classify", expect_json=True)
    obs.event("drafted", lead_id=12, type="ændringsønsker")

Logging never raises — a logging failure must not take down a run. Set LOG_DIR to
relocate. Keep the last N days only via obs.rotate() (called on run start).
"""
from __future__ import annotations
import os, re, sys, json, time, traceback, subprocess, datetime, pathlib, contextlib

LOG_DIR = pathlib.Path(os.environ.get("LOG_DIR", "data/logs"))
RUNS = LOG_DIR / "runs.jsonl"
CLAUDE = LOG_DIR / "claude.jsonl"
MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", str(8_000_000)))  # ~8MB per file


def _ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _write(path: pathlib.Path, obj: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # naive size cap: truncate-rotate to .1 when too big
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never crash a run


def event(kind: str, **fields) -> dict:
    rec = {"ts": _ts(), "kind": kind, **fields}
    _write(RUNS, rec)
    keys = ("name", "ok", "error", "lead_id", "label", "secs", "type", "state")
    extra = " ".join(f"{k}={fields[k]}" for k in keys if k in fields)
    try:
        print(f"[obs] {kind} {extra}".rstrip(), file=sys.stderr, flush=True)
    except Exception:
        pass
    return rec


@contextlib.contextmanager
def run(name: str, **ctx):
    """Wrap a script's main so its start/end/errors are always recorded."""
    t0 = time.time()
    event("run_start", name=name, **ctx)
    try:
        yield
    except BaseException as e:  # noqa: BLE001 — we re-raise after logging
        event("run_error", name=name, error=f"{type(e).__name__}: {e}",
              traceback=traceback.format_exc()[-4000:], secs=round(time.time() - t0, 1))
        raise
    else:
        event("run_end", name=name, ok=True, secs=round(time.time() - t0, 1))


def _extract_json(raw: str):
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None, "no json object found"
    try:
        return json.loads(m.group(0)), None
    except Exception as e:  # noqa: BLE001
        return None, f"json parse: {e}"


def claude(cmd: str, prompt: str, label: str = "claude", timeout: int = 180,
           expect_json: bool = False, allowed_tools: str | None = None,
           cwd: str | None = None, model: str | None = None, log_prompt: bool = True):
    """Run `claude -p` and log everything. Returns raw str, or (raw, parsed) when
    expect_json. Raises on non-zero exit (after logging). Captures Claude's own
    `rationale` field if the JSON includes one. `model` pins a specific model
    (e.g. so an evaluator runs on a different model than the implementer)."""
    t0 = time.time()
    rec = {"ts": _ts(), "label": label, "expect_json": expect_json, "cwd": cwd, "model": model}
    if log_prompt:
        rec["prompt"] = (prompt or "")[:6000]
    args = [cmd, "-p"]
    if model:
        args += ["--model", model]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]
    try:
        r = subprocess.run(args, input=prompt, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=f"{type(e).__name__}: {e}",
                   secs=round(time.time() - t0, 1))
        _write(CLAUDE, rec)
        event("claude_error", label=label, error=str(e)[:200])
        raise
    raw = (r.stdout or "").strip()
    rec.update(returncode=r.returncode, raw=raw[:8000],
               stderr=(r.stderr or "")[:1200], secs=round(time.time() - t0, 1))
    parsed = None
    if expect_json:
        parsed, perr = _extract_json(raw)
        rec["parsed"] = parsed
        if perr:
            rec["parse_error"] = perr
        if isinstance(parsed, dict) and parsed.get("rationale"):
            rec["rationale"] = str(parsed["rationale"])[:600]
    rec["ok"] = (r.returncode == 0) and (not expect_json or parsed is not None)
    _write(CLAUDE, rec)
    tail = f" rationale={rec['rationale'][:90]}" if rec.get("rationale") else ""
    try:
        print(f"[obs] claude {label} ok={rec['ok']} secs={rec['secs']}{tail}",
              file=sys.stderr, flush=True)
    except Exception:
        pass
    if r.returncode != 0:
        raise RuntimeError((r.stderr or raw)[:300])
    return (raw, parsed) if expect_json else raw
