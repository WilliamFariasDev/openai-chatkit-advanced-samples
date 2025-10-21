"""AttachmentStore implementation for ChatKit with Supabase and OpenAI Files API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from chatkit.store import AttachmentStore
from chatkit.types import Attachment, AttachmentCreateParams, FileAttachment, ImageAttachment
from openai import AsyncOpenAI

from .config import settings
from .database import get_db_pool

logger = logging.getLogger(__name__)


class SupabaseAttachmentStore(AttachmentStore[dict[str, Any]]):
    """Store attachments in Supabase and upload files to OpenAI Files API."""

    def __init__(self, openai_client: AsyncOpenAI):
        self.openai_client = openai_client

    @staticmethod
    def _get_user_id(context: dict[str, Any]) -> int:
        """Extract user_id from context."""
        user = context.get("user")
        if not user:
            raise ValueError("user_id is required in context")

        user_id = getattr(user, "public_user_id", None)
        if user_id is None:
            raise ValueError("public_user_id is required in user context")

        return int(user_id)

    def generate_attachment_id(self, mime_type: str, context: dict[str, Any]) -> str:
        """Generate a unique attachment ID."""
        return f"att_{uuid4().hex[:16]}"

    async def create_attachment(
        self, input: AttachmentCreateParams, context: dict[str, Any]
    ) -> Attachment:
        """Create an attachment record and return upload URL for two-phase upload."""
        user_id = self._get_user_id(context)
        attachment_id = self.generate_attachment_id(input.mime_type, context)

        now = datetime.now()

        # Create the attachment object based on type
        if input.mime_type.startswith("image/"):
            attachment = ImageAttachment(
                id=attachment_id,
                thread_id=input.thread_id,
                created_at=now,
                mime_type=input.mime_type,
                name=input.name,
                size_bytes=input.size_bytes,
                # Upload URL will be used by client to upload the file
                upload_url=f"/api/attachments/{attachment_id}/upload",
                # Preview URL can be generated later when serving the attachment
                preview_url=None,
            )
        else:
            attachment = FileAttachment(
                id=attachment_id,
                thread_id=input.thread_id,
                created_at=now,
                mime_type=input.mime_type,
                name=input.name,
                size_bytes=input.size_bytes,
                upload_url=f"/api/attachments/{attachment_id}/upload",
            )

        # Store attachment metadata in database
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.uploads (id, user_id, filename, byte_size, mime, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                attachment_id,
                user_id,
                input.name or "untitled",
                input.size_bytes or 0,
                input.mime_type,
                "pending",  # Status before upload completes
                now,
                now,
            )

        logger.info(f"Created attachment {attachment_id} for user {user_id}")
        return attachment

    async def delete_attachment(self, attachment_id: str, context: dict[str, Any]) -> None:
        """Delete an attachment and its associated OpenAI file."""
        user_id = self._get_user_id(context)
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            # Get the OpenAI file ID if it exists
            row = await conn.fetchrow(
                """
                SELECT openai_file_id FROM public.uploads
                WHERE id = $1 AND user_id = $2
                """,
                attachment_id,
                user_id,
            )

            if not row:
                logger.warning(f"Attachment {attachment_id} not found for user {user_id}")
                return

            # Delete from OpenAI if file was uploaded
            if row["openai_file_id"]:
                try:
                    await self.openai_client.files.delete(row["openai_file_id"])
                    logger.info(f"Deleted OpenAI file {row['openai_file_id']}")
                except Exception as e:
                    logger.error(f"Failed to delete OpenAI file: {e}")

            # Delete from database
            await conn.execute(
                "DELETE FROM public.uploads WHERE id = $1 AND user_id = $2",
                attachment_id,
                user_id,
            )

        logger.info(f"Deleted attachment {attachment_id}")

    async def get_attachment(self, attachment_id: str, context: dict[str, Any]) -> Attachment | None:
        """Retrieve attachment metadata."""
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
                return None

            # We need thread_id to construct the attachment object
            # For now, we'll use a placeholder - in production you'd want to track this
            thread_id = "unknown"

            if row["mime"].startswith("image/"):
                return ImageAttachment(
                    id=row["id"],
                    thread_id=thread_id,
                    created_at=row["created_at"],
                    mime_type=row["mime"],
                    name=row["filename"],
                    size_bytes=row["byte_size"],
                    preview_url=None,  # Generate on-demand if needed
                )
            else:
                return FileAttachment(
                    id=row["id"],
                    thread_id=thread_id,
                    created_at=row["created_at"],
                    mime_type=row["mime"],
                    name=row["filename"],
                    size_bytes=row["byte_size"],
                )

    async def upload_file_to_openai(
        self,
        attachment_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        context: dict[str, Any],
    ) -> str:
        """Upload file to OpenAI Files API and update the attachment record."""
        user_id = self._get_user_id(context)

        # Upload to OpenAI
        # Using purpose="assistants" instead of "user_data" to allow downloading file content later
        # Note: assistants purpose doesn't support expires_after, files are kept until explicitly deleted
        file_response = await self.openai_client.files.create(
            file=(filename, file_bytes, mime_type),
            purpose="assistants",
            expires_after={"anchor": "created_at", "seconds": 60 * 60 * 24 * 7},  # 7 days
        )

        openai_file_id = file_response.id
        logger.info(f"Uploaded file to OpenAI: {openai_file_id}")

        # Update database with OpenAI file ID
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE public.uploads
                SET openai_file_id = $1, status = $2, updated_at = $3
                WHERE id = $4 AND user_id = $5
                """,
                openai_file_id,
                "uploaded",
                datetime.now(),
                attachment_id,
                user_id,
            )

        return openai_file_id

