"""FastAPI entrypoint wiring the ChatKit server and REST endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from chatkit.server import StreamingResult
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from starlette.responses import JSONResponse

from .auth import AuthUser, get_current_user
from .chat import (
    FactAssistantServer,
    create_chatkit_server,
)
from .facts import fact_store
from .thread_file_manager import ThreadFileManager

app = FastAPI(title="ChatKit API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_chatkit_server: FactAssistantServer | None = create_chatkit_server()


def get_chatkit_server() -> FactAssistantServer:
    if _chatkit_server is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "ChatKit dependencies are missing. Install the ChatKit Python "
                "package to enable the conversational endpoint."
            ),
        )
    return _chatkit_server


@app.post("/chatkit")
async def chatkit_endpoint(
    request: Request,
    server: FactAssistantServer = Depends(get_chatkit_server),
    current_user: AuthUser = Depends(get_current_user),
) -> Response:
    payload = await request.body()
    result = await server.process(payload, {"request": request, "user": current_user})
    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")
    return JSONResponse(result)


@app.get("/facts")
async def list_facts(
    current_user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict[str, Any]:
    facts = await fact_store.list_saved()
    return {"facts": [fact.as_dict() for fact in facts]}


@app.post("/facts/{fact_id}/save")
async def save_fact(
    fact_id: str,
    current_user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict[str, Any]:
    fact = await fact_store.mark_saved(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"fact": fact.as_dict()}


@app.post("/facts/{fact_id}/discard")
async def discard_fact(
    fact_id: str,
    current_user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict[str, Any]:
    fact = await fact_store.discard(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"fact": fact.as_dict()}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/attachments/{attachment_id}/upload")
async def upload_attachment(
    attachment_id: str,
    file: UploadFile = File(...),
    server: FactAssistantServer = Depends(get_chatkit_server),
    current_user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Phase 2 of two-phase upload: Upload the actual file bytes.
    This endpoint is called after the attachment is created via ChatKit.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Read file content
    content = await file.read()

    try:
        # Upload to OpenAI and update database
        openai_file_id = await server.attachment_store.upload_file_to_openai(
            attachment_id=attachment_id,
            file_bytes=content,
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            context={"user": current_user},
        )

        return {
            "id": attachment_id,
            "openai_file_id": openai_file_id,
            "status": "uploaded",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/api/uploads/direct")
async def direct_upload(
    request: Request,
    file: UploadFile = File(...),
    thread_id: str = Form(None),
    server: FactAssistantServer = Depends(get_chatkit_server),
    current_user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Direct upload endpoint: Creates attachment and uploads file in one step.
    This is an alternative to two-phase upload.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Log request details for debugging
    logger.info(f"Direct upload request - filename: {file.filename}, thread_id: {thread_id}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # If thread_id is not provided, try to get it from form data or use a placeholder
    if not thread_id:
        form_data = await request.form()
        thread_id = form_data.get("thread_id") or form_data.get("threadId") or "unknown"
        logger.info(f"Thread ID extracted from form: {thread_id}")

    # Read file content
    content = await file.read()

    try:
        # Upload directly to OpenAI Files API
        from openai import AsyncOpenAI
        from .config import settings

        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Upload to OpenAI with 7-day expiration
        # Using purpose="assistants" instead of "user_data" to allow downloading file content later
        file_response = await openai_client.files.create(
            file=(file.filename, content, file.content_type or "application/octet-stream"),
            purpose="assistants",
        )

        openai_file_id = file_response.id
        logger.info(f"Uploaded file to OpenAI: {openai_file_id}")

        # Store metadata in database
        from datetime import datetime
        from .database import get_db_pool

        user_id = int(current_user.public_user_id)
        now = datetime.now()

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Insert and get the auto-generated UUID
            row = await conn.fetchrow(
                """
                INSERT INTO public.uploads (user_id, openai_file_id, filename, byte_size, mime, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                user_id,
                openai_file_id,
                file.filename,
                len(content),
                file.content_type or "application/octet-stream",
                "uploaded",
                now,
                now,
            )
            attachment_id = str(row["id"])

        # Attach to thread if thread_id is provided
        if thread_id and thread_id != "unknown":
            try:
                await ThreadFileManager.attach_file_to_thread(
                    thread_id, openai_file_id, user_id
                )
                logger.info(f"Attached file to thread {thread_id}")
            except Exception as e:
                logger.warning(f"Could not attach file to thread: {e}")

        # Return response in ChatKit format
        return {
            "id": attachment_id,
            "name": file.filename,
            "mime_type": file.content_type or "application/octet-stream",
            "size_bytes": len(content),
            "openai_file_id": openai_file_id,
            "thread_id": thread_id,
            "created_at": now.isoformat(),
        }

    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/api/threads/{thread_id}/files")
async def get_thread_files(
    thread_id: str,
    current_user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get all files attached to a thread."""
    user_id = int(current_user.public_user_id)
    files = await ThreadFileManager.get_thread_files(thread_id, user_id)
    return {"files": files}


@app.post("/api/threads/{thread_id}/files")
async def attach_file_to_thread(
    thread_id: str,
    openai_file_id: str = Form(...),
    current_user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Attach an uploaded file to a thread."""
    user_id = int(current_user.public_user_id)

    try:
        result = await ThreadFileManager.attach_file_to_thread(
            thread_id, openai_file_id, user_id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/threads/{thread_id}/files/{openai_file_id}")
async def detach_file_from_thread(
    thread_id: str,
    openai_file_id: str,
    current_user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove a file from a thread."""
    user_id = int(current_user.public_user_id)

    deleted = await ThreadFileManager.detach_file_from_thread(
        thread_id, openai_file_id, user_id
    )

    if not deleted:
        raise HTTPException(status_code=404, detail="File association not found")

    return {"success": True, "message": "File detached from thread"}


