import uuid
import time
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.db import db_conn
from core import event_bus
from schemas.requests import ProjectSaveRequest
from services.project_store import (
    PROJECT_ID_RE,
    ProjectCorruptError,
    ProjectNotFoundError,
    ProjectUndoUnavailableError,
    get_default_project_store,
)

router = APIRouter()


def _validate_project_id_or_400(project_id: str) -> str:
    pid = (project_id or "").strip()
    if not PROJECT_ID_RE.fullmatch(pid):
        raise HTTPException(status_code=400, detail="Invalid project id")
    return pid


class ProjectRenameRequest(BaseModel):
    name: str

@router.get("/projects")
async def list_projects():
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, video_path, duration, created_at, updated_at FROM studio_projects ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]

@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project_id = _validate_project_id_or_400(project_id)
    store = get_default_project_store()
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM studio_projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    result = dict(row)
    try:
        persisted = store.reopen(project_id)
        result["state"] = persisted["state"]
        result["can_undo"] = persisted["can_undo"]
        result["can_redo"] = persisted["can_redo"]
        result["revision"] = persisted["revision"]
        return result
    except ProjectCorruptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectNotFoundError:
        pass
    if result.get("state_json"):
        try:
            result["state"] = json.loads(result["state_json"])
        except Exception:
            result["state"] = {}
    else:
        result["state"] = {}
    return result

@router.post("/projects")
async def create_project(req: ProjectSaveRequest):
    project_id = str(uuid.uuid4())[:8]
    now = time.time()
    state_dict = req.state if isinstance(req.state, dict) else {}
    get_default_project_store().create(
        project_id=project_id,
        name=req.name,
        state=state_dict,
        video_path=req.video_path,
        audio_path=req.audio_path,
        duration=req.duration,
    )
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO studio_projects (id, name, video_path, audio_path, duration, state_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (project_id, req.name, req.video_path, req.audio_path, req.duration, json.dumps(state_dict), now, now),
        )
    event_bus.emit("projects", {"action": "created", "id": project_id})
    return {"id": project_id, "name": req.name, "created_at": now}

@router.put("/projects/{project_id}")
async def update_project(project_id: str, req: ProjectSaveRequest):
    project_id = _validate_project_id_or_400(project_id)
    state_dict = req.state if isinstance(req.state, dict) else {}
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM studio_projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        try:
            saved = get_default_project_store().save(
                project_id,
                state=state_dict,
                name=req.name,
                video_path=req.video_path,
                audio_path=req.audio_path,
                duration=req.duration,
            )
        except ProjectCorruptError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        now = saved["updated_at"]
        conn.execute(
            "UPDATE studio_projects SET name=?, video_path=?, audio_path=?, duration=?, state_json=?, updated_at=? WHERE id=?",
            (req.name, req.video_path, req.audio_path, req.duration, json.dumps(state_dict), now, project_id),
        )
    event_bus.emit("projects", {"action": "updated", "id": project_id})
    return {
        "id": project_id,
        "name": req.name,
        "updated_at": now,
        "revision": saved["revision"],
        "can_undo": saved["can_undo"],
        "can_redo": saved["can_redo"],
    }

@router.post("/projects/{project_id}/undo")
async def undo_project(project_id: str):
    project_id = _validate_project_id_or_400(project_id)
    try:
        restored = get_default_project_store().undo(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectUndoUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectCorruptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with db_conn() as conn:
        conn.execute(
            "UPDATE studio_projects SET state_json=?, updated_at=? WHERE id=?",
            (json.dumps(restored["state"]), restored["updated_at"], project_id),
        )
    event_bus.emit("projects", {"action": "undo", "id": project_id})
    return restored

@router.post("/projects/{project_id}/redo")
async def redo_project(project_id: str):
    project_id = _validate_project_id_or_400(project_id)
    try:
        restored = get_default_project_store().redo(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectUndoUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectCorruptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with db_conn() as conn:
        conn.execute(
            "UPDATE studio_projects SET state_json=?, updated_at=? WHERE id=?",
            (json.dumps(restored["state"]), restored["updated_at"], project_id),
        )
    event_bus.emit("projects", {"action": "redo", "id": project_id})
    return restored

@router.patch("/projects/{project_id}")
async def rename_project(project_id: str, req: ProjectRenameRequest):
    """Lightweight rename — updates both SQLite metadata and atomic ProjectStore envelope."""
    project_id = _validate_project_id_or_400(project_id)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name cannot be empty")
    now = time.time()
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM studio_projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        try:
            renamed = get_default_project_store().rename(project_id, name)
            now = renamed["updated_at"]
        except ProjectNotFoundError:
            pass
        except ProjectCorruptError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conn.execute(
            "UPDATE studio_projects SET name=?, updated_at=? WHERE id=?",
            (name, now, project_id),
        )
    event_bus.emit("projects", {"action": "renamed", "id": project_id})
    return {"id": project_id, "name": name, "updated_at": now}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    project_id = _validate_project_id_or_400(project_id)
    with db_conn() as conn:
        conn.execute("DELETE FROM studio_projects WHERE id=?", (project_id,))
    try:
        get_default_project_store().delete(project_id)
    except Exception:
        pass
    event_bus.emit("projects", {"action": "deleted", "id": project_id})
    return {"deleted": project_id}


# Project handoff shares the existing authenticated projects router.
from api.routers.project_bundles import router as project_bundles_router
router.include_router(project_bundles_router)
