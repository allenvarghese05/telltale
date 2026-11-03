"""Printable HTML report. Only verified and single-source findings reach it; blocked claims are counted, never shown.

Every dynamic string is HTML-escaped: the claim text came from a model and is untrusted data.
"""

from html import escape

LABEL_TEXT = {
    "PERCEPTION_LATE": "Perception / driver-assist detected the hazard late",
    "COMMAND_LATE": "The hazard was detected in time, but braking was commanded late",
    "BRAKE_ACTUATION_LATE": "Brakes built pressure too slowly",
    "LATE_HANDOFF": "System handed control back too late for a human to react",
    "UNAVOIDABLE": "Physically unavoidable: a nominal system would still have collided",
    "NO_FAULT_FOUND": "Avoidable, but no layer exceeded tolerance",
    "INCONCLUSIVE": "Inconclusive: evidence is incomplete",
}


def render_html(bundle: dict) -> str:
    """Render one case bundle as a standalone, printable HTML page."""
    verdict = bundle["verdict"]
    verified = [c for c in bundle["claims"] if c["status"] == "VERIFIED"]
    uncorroborated = [c for c in bundle["claims"] if c["status"] == "UNCORROBORATED"]
    n_blocked = sum(c["status"] == "BLOCKED" for c in bundle["claims"])

    def item(result: dict) -> str:
        claim = result["claim"]
        return f"<li>{escape(claim['text'])}<div class='ev'>{escape(' · '.join(claim['evidence']))}</div></li>"

    if verdict["status"] == "VERIFIED":
        head = (
            f"<b>Primary contributing factor:</b> "
            f"{escape(LABEL_TEXT.get(verdict['agent_label'], verdict['agent_label']))}"
            f"<div class='ok'>Concluded by the Muse Wonder investigator and independently verified by "
            f"deterministic recomputation.</div>"
        )
    else:
        head = (
            f"<b>Verdict withheld pending human review.</b> Investigator concluded "
            f"{escape(LABEL_TEXT.get(verdict['agent_label'], verdict['agent_label']))}; {escape(verdict['reason'])}."
        )
    noncausal = (
        f"<p>Faults present but not causal: {escape(', '.join(verdict['noncausal_faults']))}</p>"
        if verdict.get("noncausal_faults")
        else ""
    )
    facts = "".join(
        f"<tr><td>{escape(f['id'])}</td><td>{escape(str(f['value']))} {escape(f['unit'])}</td>"
        f"<td>{escape(f['derivation'])}</td></tr>"
        for f in bundle["facts"]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Telltale report {escape(bundle["case_id"])}</title>
<style>body{{font:14px/1.5 system-ui;max-width:860px;margin:24px auto;color:#111}}h1{{margin:0}}
.verdict{{border:2px solid #111;padding:12px;margin:16px 0}}.ok{{color:#1a7f37}}.ev{{color:#666;font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}td{{border-top:1px solid #ddd;padding:4px}}
@media print{{button{{display:none}}}}</style></head><body>
<button onclick="window.print()">Save as PDF</button>
<h1>Telltale incident reconstruction</h1>
<p>Case {escape(bundle["case_id"])} · profile {escape(bundle["profile"])}</p>
<div class="verdict">{head}{noncausal}</div>
<h2>Verified findings</h2><ol>{"".join(item(c) for c in verified)}</ol>
<h2>Single-source observations (not independently confirmed)</h2>
<ul>{"".join(item(c) for c in uncorroborated) or "<li>none</li>"}</ul>
<p><b>{n_blocked} claim{"s" if n_blocked != 1 else ""} blocked</b> by the deterministic checker.</p>
<h2>Evidence</h2><table>{facts}</table>
<p class="ev">Evidence digest (SHA-256): {escape(bundle["digest"])}</p>
<p class="ev">This report reconstructs evidence. It does not assign legal fault.
A qualified human reviewer must sign off.</p>
</body></html>"""
