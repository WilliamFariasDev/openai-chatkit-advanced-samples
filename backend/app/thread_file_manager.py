"""Manage file associations with threads."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from .database import get_db_pool

logger = logging.getLogger(__name__)


class ThreadFileManager:
    """Manage associations between threads and OpenAI files."""

    @staticmethod
    async def attach_file_to_thread(
        thread_id: str,
        openai_file_id: str,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Attach a file to a thread.

        Args:
            thread_id: The ChatKit thread ID (openai_conversation_id)
            openai_file_id: The OpenAI file ID
            user_id: The user ID for authorization

        Returns:
            The created thread_file record
        """
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            # First, verify the thread belongs to the user
            thread_row = await conn.fetchrow(
                """
                SELECT id FROM public.threads
                WHERE openai_conversation_id = $1 AND user_id = $2
                """,
                thread_id,
                user_id,
            )

            if not thread_row:
                raise ValueError(f"Thread {thread_id} not found or access denied")

            db_thread_id = thread_row["id"]

            # Check if association already exists
            existing = await conn.fetchrow(
                """
                SELECT id FROM public.thread_files
                WHERE thread_id = $1 AND openai_file_id = $2
                """,
                db_thread_id,
                openai_file_id,
            )

            if existing:
                logger.info(f"File {openai_file_id} already attached to thread {thread_id}")
                return {
                    "id": existing["id"],
                    "thread_id": thread_id,
                    "openai_file_id": openai_file_id,
                    "already_exists": True,
                }

            # Create the association
            now = datetime.now()
            thread_file_id = str(uuid4())

            await conn.execute(
                """
                INSERT INTO public.thread_files (id, thread_id, openai_file_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                thread_file_id,
                db_thread_id,
                openai_file_id,
                now,
                now,
            )

            logger.info(f"Attached file {openai_file_id} to thread {thread_id}")

            return {
                "id": thread_file_id,
                "thread_id": thread_id,
                "openai_file_id": openai_file_id,
                "created_at": now,
            }

    @staticmethod
    async def get_thread_files(thread_id: str, user_id: int) -> list[dict[str, Any]]:
        """
        Get all files attached to a thread.

        Args:
            thread_id: The ChatKit thread ID (openai_conversation_id)
            user_id: The user ID for authorization

        Returns:
            List of file records with metadata
        """
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            # Get thread database ID
            thread_row = await conn.fetchrow(
                """
                SELECT id FROM public.threads
                WHERE openai_conversation_id = $1 AND user_id = $2
                """,
                thread_id,
                user_id,
            )

            if not thread_row:
                return []

            db_thread_id = thread_row["id"]

            # Get all files for this thread with upload metadata
            rows = await conn.fetch(
                """
                SELECT 
                    tf.id,
                    tf.openai_file_id,
                    tf.created_at,
                    u.filename,
                    u.byte_size,
                    u.mime,
                    u.status
                FROM public.thread_files tf
                LEFT JOIN public.uploads u ON u.openai_file_id = tf.openai_file_id
                WHERE tf.thread_id = $1
                ORDER BY tf.created_at DESC
                """,
                db_thread_id,
            )

            return [
                {
                    "id": row["id"],
                    "openai_file_id": row["openai_file_id"],
                    "filename": row["filename"],
                    "byte_size": row["byte_size"],
                    "mime": row["mime"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    @staticmethod
    async def detach_file_from_thread(
        thread_id: str,
        openai_file_id: str,
        user_id: int,
    ) -> bool:
        """
        Remove a file association from a thread.

        Args:
            thread_id: The ChatKit thread ID
            openai_file_id: The OpenAI file ID
            user_id: The user ID for authorization

        Returns:
            True if deleted, False if not found
        """
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            # Get thread database ID
            thread_row = await conn.fetchrow(
                """
                SELECT id FROM public.threads
                WHERE openai_conversation_id = $1 AND user_id = $2
                """,
                thread_id,
                user_id,
            )

            if not thread_row:
                return False

            db_thread_id = thread_row["id"]

            # Delete the association
            result = await conn.execute(
                """
                DELETE FROM public.thread_files
                WHERE thread_id = $1 AND openai_file_id = $2
                """,
                db_thread_id,
                openai_file_id,
            )

            deleted = result.split()[-1] == "1"

            if deleted:
                logger.info(f"Detached file {openai_file_id} from thread {thread_id}")

            return deleted

    @staticmethod
    async def get_file_ids_for_thread(thread_id: str, user_id: int) -> list[str]:
        """
        Get just the OpenAI file IDs for a thread.
        Useful when creating OpenAI Assistant runs.

        Args:
            thread_id: The ChatKit thread ID
            user_id: The user ID for authorization

        Returns:
            List of OpenAI file IDs
        """
        files = await ThreadFileManager.get_thread_files(thread_id, user_id)
        return [f["openai_file_id"] for f in files if f["openai_file_id"]]

