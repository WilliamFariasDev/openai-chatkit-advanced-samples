"""Custom ThreadItemConverter to handle attachments with OpenAI Files API."""

from __future__ import annotations

import base64
import logging
from typing import Any

from chatkit.agents import ThreadItemConverter
from chatkit.types import Attachment, FileAttachment, ImageAttachment
from openai.types.responses import ResponseInputContentParam, ResponseInputFileParam, ResponseInputImageParam

from .database import get_db_pool

logger = logging.getLogger(__name__)


async def read_attachment_bytes(attachment_id: str, user_id: int) -> bytes | None:
    """
    Read attachment bytes from storage.

    In this implementation, we don't store the actual file bytes locally.
    Instead, we rely on the OpenAI Files API where files are already uploaded.
    This function is here for compatibility with the base64 approach if needed.
    """
    # Since we upload to OpenAI directly, we don't need to store bytes locally
    # This would be used if you wanted to store files in S3 or local storage
    logger.warning(f"read_attachment_bytes called for {attachment_id} - not implemented for OpenAI Files API approach")
    return None


async def get_openai_file_id(attachment_id: str, user_id: int) -> str | None:
    """Get the OpenAI file ID for an attachment."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT openai_file_id FROM public.uploads
            WHERE id = $1 AND user_id = $2 AND openai_file_id IS NOT NULL
            """,
            attachment_id,
            user_id,
        )
        return row["openai_file_id"] if row else None


class OpenAIFileThreadItemConverter(ThreadItemConverter):
    """
    Custom converter that uses OpenAI Files API for attachments.

    This approach uploads files to OpenAI and references them by file ID,
    which is more efficient than base64 encoding for large files.
    """

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def attachment_to_message_content(
        self, input: Attachment
    ) -> ResponseInputContentParam:
        """
        Convert attachment to Agent SDK input using OpenAI file ID.

        For images, we use the file:// URL format with the OpenAI file ID.
        For PDFs, we use the file ID directly.
        For text files, we download and include as text since OpenAI only supports PDFs for context stuffing.
        """
        # Get the OpenAI file ID from our database
        openai_file_id = await get_openai_file_id(input.id, self.user_id)

        if not openai_file_id:
            logger.error(f"No OpenAI file ID found for attachment {input.id}")
            raise ValueError(f"File {input.name} has not been uploaded yet")

        if isinstance(input, ImageAttachment):
            # For images, use the file:// URL format
            return ResponseInputImageParam(
                type="input_image",
                detail="auto",
                image_url=f"file://{openai_file_id}",
            )

        # For PDFs, use file_id with Code Interpreter
        # The Code Interpreter tool needs to be enabled in the Agent
        if input.mime_type == "application/pdf":
            logger.info(f"PDF file {input.name} will be processed with Code Interpreter, file_id: {openai_file_id}")
            return ResponseInputFileParam(
                type="input_file",
                file_id=openai_file_id,
            )

        # For other file types, inform the assistant
        logger.info(f"File {input.name} ({input.mime_type}) uploaded with ID {openai_file_id}")
        from openai.types.responses import ResponseInputTextParam
        return ResponseInputTextParam(
            type="input_text",
            text=f"[User has attached a file: {input.name} ({input.mime_type}). OpenAI File ID: {openai_file_id}]",
        )


class Base64ThreadItemConverter(ThreadItemConverter):
    """
    Alternative converter that uses base64-encoded payloads.

    This approach embeds the file content directly in the request,
    which can be useful for small files or when you want to avoid
    storing files in OpenAI.
    """

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def attachment_to_message_content(
        self, input: Attachment
    ) -> ResponseInputContentParam:
        """Convert attachment to base64-encoded content."""
        # This would require storing file bytes locally
        content = await read_attachment_bytes(input.id, self.user_id)

        if content is None:
            raise ValueError(f"Could not read file content for {input.id}")

        data = (
            "data:"
            + str(input.mime_type)
            + ";base64,"
            + base64.b64encode(content).decode("utf-8")
        )

        if isinstance(input, ImageAttachment):
            return ResponseInputImageParam(
                type="input_image",
                detail="auto",
                image_url=data,
            )

        # Note: Agents SDK currently only supports pdf files as ResponseInputFileParam
        return ResponseInputFileParam(
            type="input_file",
            file_data=data,
            filename=input.name or "unknown",
        )

