"""Messaging adapter -- **SIMULATED**.

Creates drafts and Slack notifications in memory. Nothing is sent anywhere.

**There is no send method, here or in the port.** Sending email is Tier 3 -- not a
capability this system has. A `send_email` that the policy layer always denied would
still be a system that can send email; this is a system that cannot.

## What changes when this becomes real

**API.** Gmail `users.drafts.create` with a base64url-encoded RFC 2822 message, or
Microsoft Graph `/me/messages` with `isDraft: true`. Slack `chat.postMessage` with
Block Kit for the approval notification.

**Auth.** Gmail needs `gmail.compose` -- a *write* scope on a user's mailbox, and the
one an admin will scrutinise hardest. Slack needs a bot token with `chat:write` and
membership of the target channel. Both are per-workspace.

**Rate limits.** Gmail: 250 quota units/user/second; draft creation is 10 units. Slack:
roughly one message per second per channel, bursts tolerated briefly, `429` with
`Retry-After`.

**Fields that differ.** A real draft needs a resolved RFC 5322 address, not our
`recipient_ref` -- so this call gains a contact-resolution step that can fail or,
worse, resolve to the wrong person. Threading requires `threadId` and `References`
headers to avoid starting a new conversation. Slack `channel_ref` becomes a channel id
(`C0123ABCD`), and posting to a channel the bot is not in fails with
`not_in_channel` rather than a permission error.

**Idempotency.** The one that matters. Gmail draft creation is **not** idempotent --
calling it twice creates two drafts. That is precisely why `action_records` has a
UNIQUE `idempotency_key` (Session 6): the guarantee has to come from us, because the
provider will not supply it.
"""

from __future__ import annotations

from typing import Final
from uuid import uuid4

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.integrations.status import SIMULATED

INTEGRATION_STATUS: Final = SIMULATED


class SimulatedMessagingAdapter:
    """Fixture-backed messaging. Creates drafts; sends nothing."""

    def __init__(self, behaviour: SimulatedBehaviour) -> None:
        self._behaviour = behaviour

    def create_email_draft(
        self, *, account_ref: str, recipient_ref: str, subject: str, body: str, intent: str
    ) -> JSONObject:
        self._behaviour.before_call("messaging_create_email_draft")
        return {
            "draft_ref": f"DRF-{uuid4().hex[:8].upper()}",
            "account_ref": account_ref,
            "recipient_ref": recipient_ref,
            "subject": subject,
            "body": body,
            "intent": intent,
            "created": True,
            "sent": False,
            "note": "A draft was created. Nothing was sent; sending is not a capability.",
        }

    def send_slack_approval(
        self, *, channel_ref: str, incident_ref: str, summary: str
    ) -> JSONObject:
        self._behaviour.before_call("messaging_send_slack_approval")
        return {
            "message_ref": f"MSG-{uuid4().hex[:8].upper()}",
            "channel_ref": channel_ref,
            "incident_ref": incident_ref,
            "summary": summary,
            "delivered": True,
        }
