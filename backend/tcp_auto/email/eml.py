"""Email draft (.eml) with the report attached. Outlook opens it as an unsent message
(``X-Unsent: 1``), so the user reviews and sends it from their own mailbox. No IT setup needed."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate

from ..models import Project
from ..rules.engine import resolve


def recipient_for(project: Project) -> str:
    sub = resolve(project.details).get("tcp_submittal") or {}
    if isinstance(sub, dict):
        for k in ("email", "recipient"):
            if sub.get(k):
                return str(sub[k])
        if isinstance(sub.get("amendments"), str) and "@" in sub["amendments"]:
            return sub["amendments"]
    return ""


def build_eml(project: Project, pdf: bytes, filename: str, to: str | None = None) -> bytes:
    d = project.details
    msg = EmailMessage()
    msg["To"] = to if to is not None else recipient_for(project)
    loc = d.address or (project.road.name if project.road else "")
    msg["Subject"] = f"Traffic Control Plan for review – {loc}{', ' + d.city if d.city else ''}" + (f" (Permit {d.permit_number})" if d.permit_number else "")
    msg["Date"] = formatdate(localtime=True)
    msg["X-Unsent"] = "1"
    dates = ""
    if d.phases:
        start = min(p.start_date for p in d.phases)
        end = max(p.end_date for p in d.phases)
        dates = f" from {start:%b %d} to {end:%b %d, %Y}"
    body = (
        "Hello,\n\n"
        f"Attached is the traffic control plan for {d.utility_name} work at {loc}{dates}"
        + (f" (job {d.job_number})" if d.job_number else "")
        + ". It includes a map of the layout, a short explanation, and the timeline.\n\n"
        "Please let me know if you need any changes or additional information.\n\n"
        f"Thank you,\n{d.contacts.preparer or ''}\n{d.contacts.preparer_phone or ''}\n"
    )
    msg.set_content(body)
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    return bytes(msg)
