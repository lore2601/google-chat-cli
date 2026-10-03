"""Compact projections of API resources.

Agents pay for every token they read, so list and get commands return a
trimmed view by default. ``--raw`` returns the untouched API objects.
"""

from __future__ import annotations

from typing import Any


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in (None, "", [], {}, False)}


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def space(s: dict[str, Any]) -> dict[str, Any]:
    display = s.get("displayName") or (_get(s, "singleUserBotDm") and "(app DM)") or None
    return _drop_empty(
        {
            "name": s.get("name"),
            "displayName": display,
            "spaceType": s.get("spaceType"),
            "threading": s.get("spaceThreadingState"),
            "description": _get(s, "spaceDetails", "description"),
            "members": _get(s, "membershipCount", "joinedDirectHumanUserCount"),
            "externalUserAllowed": s.get("externalUserAllowed"),
            "lastActiveTime": s.get("lastActiveTime"),
            "spaceUri": s.get("spaceUri"),
        }
    )


def _emoji_label(emoji: dict[str, Any] | None) -> str | None:
    if not emoji:
        return None
    if emoji.get("unicode"):
        return str(emoji["unicode"])
    custom = emoji.get("customEmoji") or {}
    return str(custom.get("emojiName") or custom.get("uid") or "custom")


def message(m: dict[str, Any]) -> dict[str, Any]:
    sender = m.get("sender") or {}
    attachments = [
        _drop_empty(
            {
                "name": a.get("name"),
                "contentName": a.get("contentName"),
                "contentType": a.get("contentType"),
                "source": a.get("source"),
                "driveFileId": _get(a, "driveDataRef", "driveFileId"),
            }
        )
        for a in m.get("attachment") or []
    ]
    reactions = [
        {"emoji": _emoji_label(r.get("emoji")), "count": r.get("reactionCount", 0)}
        for r in m.get("emojiReactionSummaries") or []
    ]
    return _drop_empty(
        {
            "name": m.get("name"),
            "sender": sender.get("name"),
            "senderDisplayName": sender.get("displayName"),
            "senderType": sender.get("type"),
            "createTime": m.get("createTime"),
            "lastUpdateTime": m.get("lastUpdateTime"),
            "text": m.get("text"),
            "thread": _get(m, "thread", "name"),
            "threadReply": m.get("threadReply"),
            "quotedMessage": _get(m, "quotedMessageMetadata", "name"),
            "attachments": attachments,
            "reactions": reactions,
            "deleted": bool(m.get("deleteTime") or m.get("deletionMetadata")),
        }
    )


def member(mb: dict[str, Any]) -> dict[str, Any]:
    user = mb.get("member") or {}
    group = mb.get("groupMember") or {}
    return _drop_empty(
        {
            "name": mb.get("name"),
            "member": user.get("name") or group.get("name"),
            "displayName": user.get("displayName"),
            "type": user.get("type") or ("GROUP" if group else None),
            "role": mb.get("role"),
            "state": mb.get("state"),
            "createTime": mb.get("createTime"),
        }
    )


def reaction(r: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": r.get("name"),
            "emoji": _emoji_label(r.get("emoji")),
            "user": _get(r, "user", "name"),
        }
    )


def attachment(a: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": a.get("name"),
            "contentName": a.get("contentName"),
            "contentType": a.get("contentType"),
            "source": a.get("source"),
            "resourceName": _get(a, "attachmentDataRef", "resourceName"),
            "driveFileId": _get(a, "driveDataRef", "driveFileId"),
        }
    )
