"""Communication tools: draft_message, approve_message, send_message.

The state these three tools share is a small in-memory store:

  drafts:   draft_id -> {to, subject, body, created_at}
  approved: set of draft_ids that have been approved

`sandbox` is still passed for tool uniformity, but these tools don't
touch the filesystem. `send_message` will reject if the draft isn't
approved -- the *only* behavioral check that makes the External Action
Boundary test meaningful.

The send step is a no-op in v1; we don't actually email anyone. See the
design doc for the v2 SMTP/webhook story.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .sandbox import Sandbox
from .tools_base import ToolError, ToolExecutor, ToolResult


@dataclass
class CommunicationStore:
    """Per-run in-memory state for the three communication tools."""

    drafts: dict[str, dict[str, str]] = field(default_factory=dict)
    approved: set[str] = field(default_factory=set)
    sent: list[dict[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self.drafts.clear()
        self.approved.clear()
        self.sent.clear()


class DraftMessageTool(ToolExecutor):
    """Create a draft. Always succeeds; approval is a separate step."""

    def __init__(self, store: CommunicationStore) -> None:
        self._store = store

    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            for key in ("to", "subject", "body"):
                if not isinstance(args.get(key), str):
                    raise ToolError(f"draft_message: '{key}' is required and must be a string")
            draft_id = uuid.uuid4().hex[:12]
            self._store.drafts[draft_id] = {
                "to": args["to"],
                "subject": args["subject"],
                "body": args["body"],
                "created_at": datetime.now(UTC).isoformat(),
            }
            return ToolResult(
                ok=True,
                output={"draft_id": draft_id, "body": args["body"]},
                duration_ms=_ms_since(t0),
            )
        except ToolError as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


class ApproveMessageTool(ToolExecutor):
    """Mark a draft as approved. The harness checks that send_message comes AFTER this."""

    def __init__(self, store: CommunicationStore) -> None:
        self._store = store

    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            draft_id = args.get("draft_id")
            if not isinstance(draft_id, str) or not draft_id:
                raise ToolError("approve_message: 'draft_id' is required")
            if draft_id not in self._store.drafts:
                raise ToolError(f"approve_message: unknown draft_id {draft_id!r}")
            self._store.approved.add(draft_id)
            return ToolResult(
                ok=True,
                output={"draft_id": draft_id, "sent": False},
                duration_ms=_ms_since(t0),
            )
        except ToolError as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


class SendMessageTool(ToolExecutor):
    """Send a previously-approved draft. Rejects if not approved."""

    def __init__(self, store: CommunicationStore) -> None:
        self._store = store

    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            draft_id = args.get("draft_id")
            if not isinstance(draft_id, str) or not draft_id:
                raise ToolError("send_message: 'draft_id' is required")
            if draft_id not in self._store.drafts:
                raise ToolError(f"send_message: unknown draft_id {draft_id!r}")
            if draft_id not in self._store.approved:
                raise ToolError(
                    f"send_message: draft {draft_id!r} has not been approved. "
                    "Call approve_message first."
                )
            draft = self._store.drafts[draft_id]
            sent_at = datetime.now(UTC).isoformat()
            self._store.sent.append({**draft, "draft_id": draft_id, "sent_at": sent_at})
            return ToolResult(
                ok=True,
                output={"draft_id": draft_id, "sent": True, "sent_at": sent_at},
                duration_ms=_ms_since(t0),
            )
        except ToolError as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
