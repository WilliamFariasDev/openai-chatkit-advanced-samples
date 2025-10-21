"""PostgreSQL-based implementation of ChatKit Store interface - SIMPLIFIED VERSION.

This version uses a simplified schema where ThreadItem objects are stored directly
in a JSONB column, eliminating the need for role/content extraction and conversion logic.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from chatkit.store import NotFoundError, Store
from chatkit.types import Attachment, Page, Thread, ThreadItem, ThreadMetadata

from .database import get_db_pool


# TypeAdapter for converting dictionaries to ThreadItem objects
_thread_item_adapter = TypeAdapter(ThreadItem)


def _serialize_for_json(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO format strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {key: _serialize_for_json(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    return obj


class PostgresStoreSimplified(Store[dict[str, Any]]):
    """PostgreSQL store with simplified schema - stores ThreadItem directly in JSONB."""

    @staticmethod
    def _coerce_thread_metadata(thread: ThreadMetadata | Thread) -> ThreadMetadata:
        """Return thread metadata without any embedded items."""
        has_items = isinstance(thread, Thread) or "items" in getattr(
            thread, "model_fields_set", set()
        )
        if not has_items:
            return thread.model_copy(deep=True)

        data = thread.model_dump()
        data.pop("items", None)
        return ThreadMetadata(**data).model_copy(deep=True)

    @staticmethod
    def _get_user_id(context: dict[str, Any]) -> int:
        """Extract user_id from context. Raises if not found."""
        user = context.get("user")
        if not user:
            raise ValueError("user_id is required in context")

        user_id = getattr(user, "public_user_id", None)
        if user_id is None:
            raise ValueError("public_user_id is required in user context")

        return int(user_id)

    # -- Thread metadata -------------------------------------------------
    async def load_thread(self, thread_id: str, context: dict[str, Any]) -> ThreadMetadata:
        """Load thread by openai_conversation_id (ChatKit thread ID)."""
        user_id = self._get_user_id(context)
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, title, metadata, created_at, updated_at, openai_conversation_id
                FROM public.threads
                WHERE openai_conversation_id = $1 AND user_id = $2
                """,
                thread_id,
                user_id,
            )

            if not row:
                raise NotFoundError(f"Thread {thread_id} not found")

            return ThreadMetadata(
                id=thread_id,
                created_at=row["created_at"],
                title=row["title"],
                metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {}),
            )

    async def save_thread(self, thread: ThreadMetadata, context: dict[str, Any]) -> None:
        """Save thread using openai_conversation_id (ChatKit thread ID)."""
        user_id = self._get_user_id(context)
        metadata = self._coerce_thread_metadata(thread)
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM public.threads WHERE openai_conversation_id = $1 AND user_id = $2",
                thread.id,
                user_id,
            )

            if existing:
                await conn.execute(
                    """
                    UPDATE public.threads
                    SET title = $1, metadata = $2, updated_at = $3
                    WHERE openai_conversation_id = $4 AND user_id = $5
                    """,
                    metadata.title,
                    json.dumps(metadata.metadata or {}),
                    datetime.now(),
                    thread.id,
                    user_id,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO public.threads (user_id, openai_conversation_id, title, metadata, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    user_id,
                    thread.id,
                    metadata.title,
                    json.dumps(metadata.metadata or {}),
                    datetime.now(),
                    datetime.now(),
                )

    async def load_threads(
        self,
        limit: int,
        after: str | None,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadMetadata]:
        user_id = self._get_user_id(context)
        pool = await get_db_pool()
        order_clause = "DESC" if order == "desc" else "ASC"

        async with pool.acquire() as conn:
            if after:
                after_row = await conn.fetchrow(
                    "SELECT created_at FROM public.threads WHERE openai_conversation_id = $1",
                    after,
                )
                if not after_row:
                    rows = []
                else:
                    after_time = after_row["created_at"]
                    comparison = "<" if order == "desc" else ">"
                    rows = await conn.fetch(
                        f"""
                        SELECT id, user_id, title, metadata, created_at, updated_at, openai_conversation_id
                        FROM public.threads
                        WHERE user_id = $1 AND created_at {comparison} $2
                        ORDER BY created_at {order_clause}
                        LIMIT $3
                        """,
                        user_id,
                        after_time,
                        limit + 1,
                    )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT id, user_id, title, metadata, created_at, updated_at, openai_conversation_id
                    FROM public.threads
                    WHERE user_id = $1
                    ORDER BY created_at {order_clause}
                    LIMIT $2
                    """,
                    user_id,
                    limit + 1,
                )

            has_more = len(rows) > limit
            rows = rows[:limit]

            threads = [
                ThreadMetadata(
                    id=row["openai_conversation_id"] or str(row["id"]),
                    created_at=row["created_at"],
                    title=row["title"],
                    metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {}),
                )
                for row in rows
            ]

            next_after = threads[-1].id if has_more and threads else None
            return Page(data=threads, has_more=has_more, after=next_after)

    async def delete_thread(self, thread_id: str, context: dict[str, Any]) -> None:
        user_id = self._get_user_id(context)
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            thread_row = await conn.fetchrow(
                "SELECT id FROM public.threads WHERE openai_conversation_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )

            if not thread_row:
                return

            db_thread_id = thread_row["id"]

            await conn.execute(
                "DELETE FROM public.messages WHERE thread_id = $1",
                db_thread_id,
            )

            await conn.execute(
                "DELETE FROM public.threads WHERE id = $1",
                db_thread_id,
            )

    # -- Thread items - SIMPLIFIED VERSION ----------------------------------------------------
    async def load_thread_items(
        self,
        thread_id: str,
        after: str | None,
        limit: int,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadItem]:
        pool = await get_db_pool()
        order_clause = "DESC" if order == "desc" else "ASC"

        async with pool.acquire() as conn:
            user_id = self._get_user_id(context)
            thread_row = await conn.fetchrow(
                "SELECT id FROM public.threads WHERE openai_conversation_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )
            if not thread_row:
                raise NotFoundError(f"Thread {thread_id} not found")

            db_thread_id = thread_row["id"]

            # Build query
            if after:
                after_row = await conn.fetchrow(
                    "SELECT created_at FROM public.messages WHERE openai_message_id = $1",
                    after,
                )
                if not after_row:
                    rows = []
                else:
                    after_time = after_row["created_at"]
                    comparison = "<" if order == "desc" else ">"
                    rows = await conn.fetch(
                        f"""
                        SELECT item, created_at, openai_message_id
                        FROM public.messages
                        WHERE thread_id = $1 AND created_at {comparison} $2
                        ORDER BY created_at {order_clause}
                        LIMIT $3
                        """,
                        db_thread_id,
                        after_time,
                        limit + 1,
                    )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT item, created_at, openai_message_id
                    FROM public.messages
                    WHERE thread_id = $1
                    ORDER BY created_at {order_clause}
                    LIMIT $2
                    """,
                    db_thread_id,
                    limit + 1,
                )

            has_more = len(rows) > limit
            rows = rows[:limit]

            # Convert JSONB to ThreadItem objects
            items = []
            for row in rows:
                item_data = row["item"] if isinstance(row["item"], dict) else json.loads(row["item"])
                
                # Ensure consistency with database values
                item_data["id"] = row["openai_message_id"]
                item_data["thread_id"] = thread_id
                
                # Convert to Pydantic object
                thread_item = _thread_item_adapter.validate_python(item_data)
                items.append(thread_item)

            next_after = items[-1].id if has_more and items else None
            return Page(data=items, has_more=has_more, after=next_after)

    async def add_thread_item(
        self, thread_id: str, item: ThreadItem, context: dict[str, Any]
    ) -> None:
        pool = await get_db_pool()
        user_id = self._get_user_id(context)

        async with pool.acquire() as conn:
            thread_row = await conn.fetchrow(
                "SELECT id FROM public.threads WHERE openai_conversation_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )
            if not thread_row:
                raise NotFoundError(f"Thread {thread_id} not found")

            db_thread_id = thread_row["id"]

            # Convert ThreadItem to dict and serialize
            item_dict = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            item_json = _serialize_for_json(item_dict)

            await conn.execute(
                """
                INSERT INTO public.messages
                (thread_id, openai_message_id, item, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                db_thread_id,
                item.id,
                json.dumps(item_json),
                item_dict.get("created_at", datetime.now()),
                datetime.now(),
            )

    async def save_item(self, thread_id: str, item: ThreadItem, context: dict[str, Any]) -> None:
        pool = await get_db_pool()
        user_id = self._get_user_id(context)

        async with pool.acquire() as conn:
            thread_row = await conn.fetchrow(
                "SELECT id FROM public.threads WHERE openai_conversation_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )
            if not thread_row:
                raise NotFoundError(f"Thread {thread_id} not found")

            db_thread_id = thread_row["id"]

            existing = await conn.fetchrow(
                "SELECT id FROM public.messages WHERE openai_message_id = $1 AND thread_id = $2",
                item.id,
                db_thread_id,
            )

            item_dict = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            item_json = _serialize_for_json(item_dict)

            if existing:
                await conn.execute(
                    """
                    UPDATE public.messages
                    SET item = $1, updated_at = $2
                    WHERE id = $3
                    """,
                    json.dumps(item_json),
                    datetime.now(),
                    existing["id"],
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO public.messages
                    (thread_id, openai_message_id, item, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    db_thread_id,
                    item.id,
                    json.dumps(item_json),
                    item_dict.get("created_at", datetime.now()),
                    datetime.now(),
                )

    async def load_item(self, thread_id: str, item_id: str, context: dict[str, Any]) -> ThreadItem:
        pool = await get_db_pool()
        user_id = self._get_user_id(context)

        async with pool.acquire() as conn:
            thread_row = await conn.fetchrow(
                "SELECT id FROM public.threads WHERE openai_conversation_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )
            if not thread_row:
                raise NotFoundError(f"Thread {thread_id} not found")

            db_thread_id = thread_row["id"]

            row = await conn.fetchrow(
                """
                SELECT item, openai_message_id
                FROM public.messages
                WHERE openai_message_id = $1 AND thread_id = $2
                """,
                item_id,
                db_thread_id,
            )

            if not row:
                raise NotFoundError(f"Item {item_id} not found")

            item_data = row["item"] if isinstance(row["item"], dict) else json.loads(row["item"])
            item_data["id"] = row["openai_message_id"]
            item_data["thread_id"] = thread_id

            thread_item = _thread_item_adapter.validate_python(item_data)
            return thread_item

    async def delete_thread_item(
        self, thread_id: str, item_id: str, context: dict[str, Any]
    ) -> None:
        pool = await get_db_pool()
        user_id = self._get_user_id(context)

        async with pool.acquire() as conn:
            thread_row = await conn.fetchrow(
                "SELECT id FROM public.threads WHERE openai_conversation_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )
            if not thread_row:
                return

            db_thread_id = thread_row["id"]

            await conn.execute(
                """
                DELETE FROM public.messages
                WHERE openai_message_id = $1 AND thread_id = $2
                """,
                item_id,
                db_thread_id,
            )

    # -- Files -----------------------------------------------------------
    async def save_attachment(
        self,
        attachment: Attachment,
        context: dict[str, Any],
    ) -> None:
        raise NotImplementedError("Attachment support not yet implemented")

    async def load_attachment(
        self,
        attachment_id: str,
        context: dict[str, Any],
    ) -> Attachment:
        """Load attachment metadata from database."""
        from chatkit.types import FileAttachment, ImageAttachment

        user_id = self._get_user_id(context)
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, filename, byte_size, mime, openai_file_id, created_at
                FROM public.uploads
                WHERE id = $1 AND user_id = $2
                """,
                attachment_id,
                user_id,
            )

            if not row:
                raise NotFoundError(f"Attachment {attachment_id} not found")

            # Create appropriate attachment type based on mime type
            if row["mime"].startswith("image/"):
                return ImageAttachment(
                    id=str(row["id"]),
                    thread_id="",  # Thread ID is not stored in uploads table
                    created_at=row["created_at"],
                    mime_type=row["mime"],
                    name=row["filename"],
                    size_bytes=row["byte_size"],
                    preview_url=None,
                )
            else:
                return FileAttachment(
                    id=str(row["id"]),
                    thread_id="",  # Thread ID is not stored in uploads table
                    created_at=row["created_at"],
                    mime_type=row["mime"],
                    name=row["filename"],
                    size_bytes=row["byte_size"],
                )

    async def delete_attachment(self, attachment_id: str, context: dict[str, Any]) -> None:
        """Delete attachment from database."""
        user_id = self._get_user_id(context)
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM public.uploads WHERE id = $1 AND user_id = $2",
                attachment_id,
                user_id,
            )

