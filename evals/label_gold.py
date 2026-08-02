"""label_gold.py — a local labelling workbench for building data/gold/gold.csv.

`GOLD_REQUIREMENTS.md` §D.1 refers to "the labelling tool". There wasn't one in
this repo. This is it.

WHAT THIS PROGRAM DOES NOT CONTAIN: a materiality judgement. There is no
default, no pre-selection, no suggestion, no import from `triage.csv`, no
heuristic that ticks a box for you. Every `label_*`, `slice_tag` and
`difficulty` value written to `gold.csv` arrives from your keystrokes in the
browser and from nowhere else. What the tool does is the mechanical half:

  - copies the 7 identifying columns straight through from candidates.csv, so
    they can't drift from the canonical record (§A.5, §C)
  - captures the evidence span from your text selection over the real
    `body_text`, so it is verbatim by construction — the single most common way
    a hand-typed gold set fails the gate — and re-verifies it server-side
  - encodes categories with the §D.1 semicolon, stamps a tz-aware `labelled_at`
  - counts your slice quotas against 15/15/12/10/8 live, so you find out you're
    over on `hard_negative` at row 20 rather than row 60
  - saves a draft after every row, so you can stop and resume

Stdlib only — no dependency outside SPEC §3.

Run:  python -m evals.label_gold          then open http://127.0.0.1:8765
      python -m evals.label_gold --port 9000

Drafts live in out/gold_drafts.json. `gold.csv` is written only when you press
"Write gold.csv", and it is composed entirely of values you entered. Verify it
with `python -m evals.validate_gold`.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from evals.export_candidates import CANDIDATES_PATH, GOLD_COLUMNS
from evals.validate_gold import (
    CATEGORY_DELIMITER,
    DIFFICULTY_VALUES,
    GOLD_PATH,
    MAX_RATIONALE_CHARS,
    MAX_SPAN_CHARS,
    SLICE_TARGETS,
    load_candidates,
    load_bodies,
)
from src.models import Category, Materiality

ROOT = Path(__file__).resolve().parent.parent
DRAFTS_PATH = ROOT / "out" / "gold_drafts.json"

MATERIALITY_ORDER = ["material", "immaterial", "insufficient_info"]
CATEGORY_ORDER = list(Category.__args__)
DIFFICULTY_ORDER = ["easy", "medium", "hard"]

assert set(MATERIALITY_ORDER) == set(Materiality.__args__)
assert set(DIFFICULTY_ORDER) == DIFFICULTY_VALUES


# --- draft store -------------------------------------------------------------

def load_drafts() -> dict:
    if DRAFTS_PATH.is_file():
        return json.loads(DRAFTS_PATH.read_text(encoding="utf-8"))
    return {"labeller": "", "pass_number": "1", "rows": {}}


def save_drafts(drafts: dict) -> None:
    DRAFTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRAFTS_PATH.write_text(json.dumps(drafts, indent=2), encoding="utf-8")


def is_complete(draft: dict) -> bool:
    """A row counts toward quota only when the owner has supplied every field
    AND the row would survive the gate.

    The evidence span is allowed to be empty on an abstention (§D.2) and only
    there. A span that is not verbatim in body_text, or is over length, makes
    the row incomplete rather than merely warned about — otherwise the quota
    counters would tell you you're finished while `validate_gold` rejects the
    file.
    """
    if not draft.get("materiality") or not draft.get("categories"):
        return False
    if not draft.get("rationale", "").strip():
        return False
    if len(draft.get("rationale", "")) > MAX_RATIONALE_CHARS:
        return False
    if not draft.get("slice_tag") or not draft.get("difficulty"):
        return False
    span = draft.get("span", "")
    if not span.strip():
        return draft.get("materiality") == "insufficient_info"
    if len(span) > MAX_SPAN_CHARS:
        return False
    # Set by _save against the real body_text; absent on drafts written before
    # this check existed, which are re-verified on next save.
    return draft.get("span_verbatim", False)


def quota_state(drafts: dict) -> dict:
    counts = {tag: 0 for tag in SLICE_TARGETS}
    for draft in drafts["rows"].values():
        if is_complete(draft) and draft.get("slice_tag") in counts:
            counts[draft["slice_tag"]] += 1
    return {
        "counts": counts,
        "targets": SLICE_TARGETS,
        "done": sum(counts.values()),
        "total": sum(SLICE_TARGETS.values()),
    }


# --- gold.csv composition ----------------------------------------------------

def compose_gold(drafts: dict, candidates: dict) -> tuple[str, list[str]]:
    """Build gold.csv text from completed drafts. Returns (csv_text, problems).

    Identifying columns are copied from the candidate row. Label columns come
    from the draft and are not touched, normalised or inferred here.
    """
    import csv
    import io

    by_id = {c["announcement_id"]: c for c in candidates.values()}
    complete = [
        (announcement_id, draft)
        for announcement_id, draft in drafts["rows"].items()
        if is_complete(draft)
    ]
    complete.sort(key=lambda pair: int(by_id[pair[0]]["id"]) if pair[0] in by_id else 0)

    problems: list[str] = []
    labeller = drafts.get("labeller", "").strip()
    if not labeller:
        problems.append("labeller is empty — set it in the header field before writing")
    pass_number = drafts.get("pass_number", "").strip()
    if not pass_number.isdigit():
        problems.append(f"pass_number {pass_number!r} is not an integer")

    state = quota_state(drafts)
    for tag, target in SLICE_TARGETS.items():
        actual = state["counts"][tag]
        if actual != target:
            problems.append(f"slice {tag}: {actual} of {target}")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=GOLD_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for announcement_id, draft in complete:
        candidate = by_id[announcement_id]
        writer.writerow(
            {
                # Copied through — never authored here (§C).
                "id": candidate["id"],
                "announcement_id": candidate["announcement_id"],
                "exchange": candidate["exchange"],
                "ticker": candidate["ticker"],
                "published_at": candidate["published_at"],
                "doc_type": candidate["doc_type"],
                "issuer_price_sensitive_flag": "",  # EDGAR supplies no such signal
                # Authored by the owner, passed through verbatim.
                "label_materiality": draft["materiality"],
                "label_categories": CATEGORY_DELIMITER.join(draft["categories"]),
                "label_evidence_span": draft.get("span", ""),
                "label_rationale": draft["rationale"],
                "slice_tag": draft["slice_tag"],
                "difficulty": draft["difficulty"],
                "labelled_at": draft["labelled_at"],
                "labeller": labeller,
                "pass_number": pass_number,
            }
        )
    return buffer.getvalue(), problems


# --- page --------------------------------------------------------------------

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>gold.csv labelling — {ticker} {form}</title>
<style>
  :root {{ color-scheme: light dark; --line:#8883; --accent:#2563eb; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:14px/1.5 ui-sans-serif,system-ui,sans-serif; }}
  header {{ display:flex; gap:1rem; align-items:center; flex-wrap:wrap;
            padding:.6rem 1rem; border-bottom:1px solid var(--line); position:sticky; top:0;
            background:Canvas; z-index:5; }}
  header .grow {{ flex:1; }}
  .quota {{ display:flex; gap:.5rem; flex-wrap:wrap; font-size:12px; }}
  .quota span {{ padding:.15rem .45rem; border:1px solid var(--line); border-radius:99px; }}
  .quota .full {{ background:#16a34a22; border-color:#16a34a; }}
  .quota .over {{ background:#dc262622; border-color:#dc2626; }}
  main {{ display:grid; grid-template-columns: 1fr 26rem; gap:0; height:calc(100vh - 3.2rem); }}
  #doc {{ overflow:auto; padding:1rem 1.4rem; border-right:1px solid var(--line); }}
  #body {{ white-space:pre-wrap; word-wrap:break-word; font:13px/1.6 ui-monospace,monospace; }}
  aside {{ overflow:auto; padding:1rem; }}
  fieldset {{ border:1px solid var(--line); border-radius:6px; margin:0 0 .8rem; padding:.5rem .7rem; }}
  legend {{ font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  label {{ display:block; padding:.12rem 0; cursor:pointer; }}
  textarea {{ width:100%; font:inherit; }}
  .count {{ float:right; font-size:11px; opacity:.65; }}
  .span {{ min-height:3.4rem; border:1px dashed var(--line); border-radius:5px; padding:.4rem;
           font:12px/1.5 ui-monospace,monospace; white-space:pre-wrap; }}
  .hint {{ font-size:12px; opacity:.7; }}
  button {{ font:inherit; padding:.35rem .7rem; border-radius:5px; border:1px solid var(--line);
            background:Canvas; cursor:pointer; }}
  button.primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  #status {{ font-size:12px; min-height:1.2em; }}
  kbd {{ font:11px ui-monospace,monospace; border:1px solid var(--line); border-radius:3px;
         padding:0 .25rem; }}
  a {{ color:var(--accent); }}
</style>

<header>
  <strong>{position} / {pool}</strong>
  <span>#{cid} <b>{ticker}</b> · {form} · {published}</span>
  <a href="{source_url}" target="_blank" rel="noopener">source ↗</a>
  <span class="grow"></span>
  <span>labeller <input id="labeller" size="8" value="{labeller}"></span>
  <span>pass <input id="passno" size="2" value="{pass_number}"></span>
  <div class="quota" id="quota"></div>
  <button id="write" class="primary">Write gold.csv</button>
</header>

<main>
  <div id="doc">
    <h3 style="margin:.2rem 0 1rem">{headline}</h3>
    <p class="hint">Select text below to capture it as the evidence span — selecting from the
       real body text is what makes the span verbatim. {truncnote}</p>
    <div id="body">{body}</div>
  </div>

  <aside>
    <fieldset>
      <legend>Materiality <kbd>1</kbd><kbd>2</kbd><kbd>3</kbd></legend>
      {materiality_inputs}
    </fieldset>

    <fieldset>
      <legend>Categories — one or more</legend>
      {category_inputs}
    </fieldset>

    <fieldset>
      <legend>Evidence span <span class="count"><span id="spanlen">0</span>/{max_span}</span></legend>
      <div class="span" id="span"></div>
      <p class="hint">Select in the document, then <button id="usesel" type="button">use selection</button>
         <button id="clearsel" type="button">clear</button></p>
    </fieldset>

    <fieldset>
      <legend>Rationale <span class="count"><span id="ratlen">0</span>/{max_rationale}</span></legend>
      <textarea id="rationale" rows="3" maxlength="{max_rationale}"></textarea>
    </fieldset>

    <fieldset>
      <legend>Slice</legend>
      {slice_inputs}
    </fieldset>

    <fieldset>
      <legend>Difficulty</legend>
      {difficulty_inputs}
    </fieldset>

    <p>
      <button id="prev">← prev</button>
      <button id="next">next →</button>
      <button id="nextblank">next unlabelled</button>
    </p>
    <p id="status"></p>
    <p class="hint">Saves automatically on every change. Nothing here is pre-filled:
       every value is yours.</p>
  </aside>
</main>

<script>
const POS = {position}, POOL = {pool}, AID = {aid_json};
const draft = {draft_json};
const BODY = document.getElementById('body');

function val(name) {{
  const el = document.querySelector(`input[name="${{name}}"]:checked`);
  return el ? el.value : "";
}}
function cats() {{
  return [...document.querySelectorAll('input[name="cat"]:checked')].map(e => e.value);
}}
function setSpan(text) {{
  document.getElementById('span').textContent = text;
  document.getElementById('spanlen').textContent = text.length;
  document.getElementById('spanlen').style.color = text.length > {max_span} ? '#dc2626' : '';
}}

// restore
if (draft.materiality) {{
  const el = document.querySelector(`input[name="materiality"][value="${{draft.materiality}}"]`);
  if (el) el.checked = true;
}}
(draft.categories || []).forEach(c => {{
  const el = document.querySelector(`input[name="cat"][value="${{c}}"]`);
  if (el) el.checked = true;
}});
setSpan(draft.span || "");
document.getElementById('rationale').value = draft.rationale || "";
document.getElementById('ratlen').textContent = (draft.rationale || "").length;
['slice_tag','difficulty'].forEach(n => {{
  if (draft[n]) {{
    const el = document.querySelector(`input[name="${{n}}"][value="${{draft[n]}}"]`);
    if (el) el.checked = true;
  }}
}});

async function save() {{
  const payload = {{
    announcement_id: AID,
    materiality: val('materiality'),
    categories: cats(),
    span: document.getElementById('span').textContent,
    rationale: document.getElementById('rationale').value,
    slice_tag: val('slice_tag'),
    difficulty: val('difficulty'),
    labeller: document.getElementById('labeller').value,
    pass_number: document.getElementById('passno').value,
  }};
  const res = await fetch('/save', {{method:'POST', body: JSON.stringify(payload)}});
  const data = await res.json();
  renderQuota(data.quota);
  document.getElementById('status').textContent =
    data.warning ? '⚠ ' + data.warning : (data.complete ? '✓ complete' : 'saved (incomplete)');
  document.getElementById('status').style.color = data.warning ? '#dc2626' : '';
}}

function renderQuota(q) {{
  const box = document.getElementById('quota');
  box.innerHTML = '';
  for (const [tag, target] of Object.entries(q.targets)) {{
    const n = q.counts[tag];
    const s = document.createElement('span');
    s.textContent = `${{tag.replace('clear_','')}} ${{n}}/${{target}}`;
    if (n === target) s.className = 'full';
    if (n > target) s.className = 'over';
    box.appendChild(s);
  }}
  const s = document.createElement('span');
  s.textContent = `total ${{q.done}}/${{q.total}}`;
  box.appendChild(s);
}}
renderQuota({quota_json});

document.querySelectorAll('input').forEach(el => el.addEventListener('change', save));
document.getElementById('rationale').addEventListener('input', e => {{
  document.getElementById('ratlen').textContent = e.target.value.length;
}});
document.getElementById('rationale').addEventListener('blur', save);

document.getElementById('usesel').onclick = () => {{
  const sel = window.getSelection();
  if (!sel.rangeCount || !BODY.contains(sel.anchorNode)) {{
    document.getElementById('status').textContent = 'select inside the document first';
    return;
  }}
  setSpan(sel.toString());
  save();
}};
document.getElementById('clearsel').onclick = () => {{ setSpan(''); save(); }};
BODY.addEventListener('mouseup', () => {{
  const sel = window.getSelection();
  if (sel.rangeCount && sel.toString().trim() && BODY.contains(sel.anchorNode)) {{
    setSpan(sel.toString());
    save();
  }}
}});

const go = p => location.href = '/label/' + p;
document.getElementById('prev').onclick = () => go(Math.max(1, POS - 1));
document.getElementById('next').onclick = () => go(Math.min(POOL, POS + 1));
document.getElementById('nextblank').onclick = async () => {{
  const r = await fetch('/next_blank?from=' + POS);
  go((await r.json()).position);
}};
document.getElementById('write').onclick = async () => {{
  await save();
  const r = await fetch('/write', {{method:'POST'}});
  const d = await r.json();
  alert(d.message);
}};

document.addEventListener('keydown', e => {{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  const keys = {{'1':'material','2':'immaterial','3':'insufficient_info'}};
  if (keys[e.key]) {{
    document.querySelector(`input[name="materiality"][value="${{keys[e.key]}}"]`).checked = true;
    save();
  }}
  if (e.key === 'ArrowRight') go(Math.min(POOL, POS + 1));
  if (e.key === 'ArrowLeft') go(Math.max(1, POS - 1));
}});
</script>
"""


def radio_inputs(name: str, values: list[str]) -> str:
    return "".join(
        f'<label><input type="radio" name="{name}" value="{v}"> {v}</label>' for v in values
    )


def checkbox_inputs(values: list[str]) -> str:
    return "".join(
        f'<label><input type="checkbox" name="cat" value="{v}"> {v}</label>' for v in values
    )


class Workbench(BaseHTTPRequestHandler):
    candidates: list[dict] = []
    bodies: dict[str, str] = {}
    drafts: dict = {}

    def log_message(self, *args) -> None:  # quiet
        pass

    # --- helpers ---
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    # --- routes ---
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._redirect("/label/1")
            return
        if parsed.path.startswith("/label/"):
            try:
                position = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self._redirect("/label/1")
                return
            self._render(max(1, min(len(self.candidates), position)))
            return
        if parsed.path == "/next_blank":
            start = int(dict(p.split("=") for p in parsed.query.split("&") if "=" in p).get("from", 0))
            order = list(range(start, len(self.candidates))) + list(range(0, start))
            for index in order:
                announcement_id = self.candidates[index]["announcement_id"]
                if not is_complete(self.drafts["rows"].get(announcement_id, {})):
                    self._json({"position": index + 1})
                    return
            self._json({"position": start})
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/save":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._save(payload)
            return
        if parsed.path == "/write":
            self._write_gold()
            return
        self._send(404, b"not found", "text/plain")

    def _save(self, payload: dict) -> None:
        announcement_id = payload.get("announcement_id", "")
        body = self.bodies.get(announcement_id, "")
        span = payload.get("span", "")

        # The span came from a selection over body_text, so it should be verbatim.
        # Verify anyway — a selection can pick up rendering artefacts — and record
        # the result, because is_complete() gates the quota counters on it.
        span_verbatim = bool(span) and span in body

        warning = ""
        if span and not span_verbatim:
            warning = "that span is not a verbatim substring of body_text — reselect it"
        elif len(span) > MAX_SPAN_CHARS:
            warning = f"span is {len(span)} chars, over the {MAX_SPAN_CHARS} limit"
        elif len(payload.get("rationale", "")) > MAX_RATIONALE_CHARS:
            warning = f"rationale is over the {MAX_RATIONALE_CHARS}-char limit"

        draft = {
            "materiality": payload.get("materiality", ""),
            "categories": payload.get("categories", []),
            "span": span,
            "span_verbatim": span_verbatim,
            "rationale": payload.get("rationale", "").strip(),
            "slice_tag": payload.get("slice_tag", ""),
            "difficulty": payload.get("difficulty", ""),
            "labelled_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        }
        self.drafts["rows"][announcement_id] = draft
        self.drafts["labeller"] = payload.get("labeller", "")
        self.drafts["pass_number"] = payload.get("pass_number", "1")
        save_drafts(self.drafts)

        self._json(
            {
                "complete": is_complete(draft),
                "warning": warning,
                "quota": quota_state(self.drafts),
            }
        )

    def _write_gold(self) -> None:
        by_aid = {c["announcement_id"]: c for c in self.candidates}
        text, problems = compose_gold(self.drafts, by_aid)
        rows = text.count("\n") - 1
        GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLD_PATH.write_text(text, encoding="utf-8", newline="")
        message = f"Wrote {rows} labelled row(s) to data/gold/gold.csv."
        if problems:
            message += "\n\nNot yet a complete gold set:\n  - " + "\n  - ".join(problems)
        message += "\n\nVerify with:  python -m evals.validate_gold"
        print(message)
        self._json({"message": message, "rows": rows, "problems": problems})

    def _render(self, position: int) -> None:
        candidate = self.candidates[position - 1]
        announcement_id = candidate["announcement_id"]
        body = self.bodies.get(announcement_id, "(body not found in data/raw/)")
        truncated = candidate.get("truncated", "") == "true"

        page = PAGE.format(
            position=position,
            pool=len(self.candidates),
            cid=escape(candidate["id"]),
            ticker=escape(candidate["ticker"]),
            form=escape(candidate.get("native_doc_type", candidate["doc_type"])),
            published=escape(candidate["published_at"][:16]),
            source_url=escape(candidate.get("source_url", "")),
            headline=escape(candidate.get("headline", "")),
            body=escape(body),
            truncnote=(
                f"<b>Truncated at {len(body)} chars</b> — this is the head of a longer filing."
                if truncated else ""
            ),
            materiality_inputs=radio_inputs("materiality", MATERIALITY_ORDER),
            category_inputs=checkbox_inputs(CATEGORY_ORDER),
            slice_inputs=radio_inputs("slice_tag", list(SLICE_TARGETS)),
            difficulty_inputs=radio_inputs("difficulty", DIFFICULTY_ORDER),
            max_span=MAX_SPAN_CHARS,
            max_rationale=MAX_RATIONALE_CHARS,
            labeller=escape(self.drafts.get("labeller", "")),
            pass_number=escape(self.drafts.get("pass_number", "1")),
            aid_json=json.dumps(announcement_id),
            draft_json=json.dumps(self.drafts["rows"].get(announcement_id, {})),
            quota_json=json.dumps(quota_state(self.drafts)),
        )
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = parser.parse_args()

    print("Loading candidates and canonical bodies from data/raw/ (no requests)...")
    candidates = list(load_candidates().values())
    candidates.sort(key=lambda c: int(c["id"]))
    Workbench.candidates = candidates
    Workbench.bodies = load_bodies()
    Workbench.drafts = load_drafts()

    state = quota_state(Workbench.drafts)
    print(f"\n{len(candidates)} candidates. Draft progress: {state['done']}/{state['total']} complete.")
    for tag, target in SLICE_TARGETS.items():
        print(f"  {tag:<18} {state['counts'][tag]:>2} / {target}")

    url = f"http://127.0.0.1:{args.port}/"
    print(f"\nLabelling workbench: {url}")
    print("Every label is yours — nothing is pre-filled. Ctrl-C to stop; drafts are saved as you go.\n")
    if not args.no_open:
        webbrowser.open(url)

    server = HTTPServer(("127.0.0.1", args.port), Workbench)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Drafts are in out/gold_drafts.json — re-run to resume.")


if __name__ == "__main__":
    main()
