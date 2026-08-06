"""Messaging port. Real counterpart: Gmail drafts and the Slack Web API.

There is deliberately **no send method**. Sending email is Tier 3 -- not a capability
this system has. A port that declared `send_email` and a policy layer that always
denied it would still be a system that could send email; this one cannot.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject


@runtime_checkable
class MessagingPort(Protocol):
    def create_email_draft(
        self, *, account_ref: str, recipient_ref: str, subject: str, body: str, intent: str
    ) -> JSONObject: ...

    def send_slack_approval(
        self, *, channel_ref: str, incident_ref: str, summary: str
    ) -> JSONObject: ...
