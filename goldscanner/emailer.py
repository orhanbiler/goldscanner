"""Send an email digest of matching listings over SMTP."""

from __future__ import annotations

import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .models import Item, Score

log = logging.getLogger(__name__)


class Emailer:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        recipient: str,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender = sender
        self.recipient = recipient

    def send_digest(self, matches: list[tuple[Item, Score]]) -> None:
        if not matches:
            return
        subject = f"goldscanner: {len(matches)} new gold-filled enamel bangle candidate(s)"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.attach(MIMEText(self._plain(matches), "plain"))
        msg.attach(MIMEText(self._html(matches), "html"))

        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(self.user, self.password)
            server.sendmail(self.sender, [self.recipient], msg.as_string())
        log.info("Emailed digest of %d match(es) to %s", len(matches), self.recipient)

    # -- rendering -----------------------------------------------------------

    @staticmethod
    def _plain(matches: list[tuple[Item, Score]]) -> str:
        lines = ["New candidates on shopgoodwill.com:\n"]
        for item, score in matches:
            lines.append(f"- {item.title}")
            lines.append(f"  {item.url}")
            if item.current_price is not None:
                lines.append(f"  Price: ${item.current_price}  Bids: {item.num_bids or 0}")
            if item.end_time:
                lines.append(f"  Ends: {item.end_time}")
            lines.append(f"  Confidence: {score.confidence:.0%} — {score.reasoning}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _html(matches: list[tuple[Item, Score]]) -> str:
        cards = []
        for item, score in matches:
            img = item.image_urls[0] if item.image_urls else ""
            img_tag = (
                f'<img src="{html.escape(img)}" alt="" '
                'style="max-width:180px;max-height:180px;border-radius:6px;border:1px solid #ddd">'
                if img
                else ""
            )
            price = (
                f"${html.escape(str(item.current_price))}"
                if item.current_price is not None
                else "—"
            )
            cards.append(
                f"""
                <div style="display:flex;gap:16px;padding:16px 0;border-bottom:1px solid #eee">
                  <div>{img_tag}</div>
                  <div style="font-family:system-ui,Arial,sans-serif;font-size:14px;color:#222">
                    <a href="{html.escape(item.url)}" style="font-size:16px;font-weight:600;color:#1a5">
                      {html.escape(item.title)}
                    </a>
                    <div style="margin-top:6px">Price: <b>{price}</b> &nbsp; Bids: {item.num_bids or 0}</div>
                    <div style="color:#666">Ends: {html.escape(str(item.end_time or "—"))}</div>
                    <div style="margin-top:6px">
                      Match confidence: <b>{score.confidence:.0%}</b><br>
                      <span style="color:#444">{html.escape(score.reasoning)}</span>
                    </div>
                  </div>
                </div>"""
            )
        return (
            '<div style="max-width:640px;margin:0 auto">'
            '<h2 style="font-family:system-ui,Arial,sans-serif">'
            "New gold-filled enamel bangle candidates</h2>" + "".join(cards) + "</div>"
        )
