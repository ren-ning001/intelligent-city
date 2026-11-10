from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .config import PROJECT_ROOT, Settings, get_settings


Role = Literal["user", "agent", "system"]
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _workspace_segment() -> str:
    normalized = str(PROJECT_ROOT.resolve()).replace("\\", "-").replace("/", "-")
    return f"--{normalized.replace(':', '')}--"


class ConversationStore:
    """Durable application transcript stored beside each native DSH session."""

    filename = "zyourroad-chat.jsonl"
    events_filename = "zyourroad-events.jsonl"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.workspace_dir = self.settings.dsh_sessions_dir / _workspace_segment()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def validate_session_id(session_id: str) -> str:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("无效的会话ID")
        return session_id

    def session_dir(self, session_id: str) -> Path:
        return self.workspace_dir / self.validate_session_id(session_id)

    def transcript_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / self.filename

    def events_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / self.events_filename

    def _append_record(self, path: Path, record: dict[str, Any]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(
                    json.dumps(record, ensure_ascii=False, default=str)
                    + "\n"
                )
                file.flush()
                os.fsync(file.fileno())

    def append(self, session_id: str, role: Role, content: str) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "created_at": datetime.now(UTC).isoformat(),
        }
        path = self.transcript_path(session_id)
        self._append_record(path, record)
        return record

    def append_tool_notification(
        self,
        session_id: str,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        event = payload.get("event")
        if method != "session.event" or not isinstance(event, dict):
            return None
        if event.get("type") not in {"tool/call", "tool/result"}:
            return None
        record = {
            "id": str(uuid.uuid4()),
            "method": method,
            "payload": payload,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._append_record(self.events_path(session_id), record)
        return record

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        path = self.transcript_path(session_id)
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        with self._lock, path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("role") in {"user", "agent", "system"}
                    and isinstance(record.get("content"), str)
                ):
                    records.append(record)
        return records

    def events(self, session_id: str) -> list[dict[str, Any]]:
        path = self.events_path(session_id)
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        with self._lock, path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("method") == "session.event"
                    and isinstance(record.get("payload"), dict)
                ):
                    records.append(record)
        return records

    def context(self, session_id: str, limit: int = 12, max_chars: int = 12_000) -> str:
        messages = self.messages(session_id)[-limit:]
        rendered = "\n".join(
            f"{'用户' if item['role'] == 'user' else '助手'}：{item['content']}"
            for item in messages
            if item["role"] in {"user", "agent"}
        )
        return rendered[-max_chars:]

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        with self._lock:
            paths = list(self.workspace_dir.glob(f"*/{self.filename}"))
        for path in paths:
            session_id = path.parent.name
            messages = self.messages(session_id)
            if not messages:
                continue
            first_user = next(
                (item["content"] for item in messages if item["role"] == "user"),
                "新对话",
            )
            title = " ".join(first_user.split())
            sessions.append(
                {
                    "session_id": session_id,
                    "title": title[:32] + ("…" if len(title) > 32 else ""),
                    "message_count": len(messages),
                    "updated_at": datetime.fromtimestamp(
                        path.stat().st_mtime,
                        tz=UTC,
                    ).isoformat(),
                }
            )
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        return sessions


_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store
