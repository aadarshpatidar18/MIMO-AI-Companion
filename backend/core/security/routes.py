"""HTTP API for device identity. Mounted in backend/api.py under no prefix."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import get_service
from .gate import current_device, require_scope
from .tokens import DEVICE_KINDS

router = APIRouter(tags=["security"])

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class PairBody(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    name: str = Field(default=None, max_length=64)
    kind: str = Field(default="android", max_length=16)


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SettingsBody(BaseModel):
    require_auth: bool


def _is_local(request: Request) -> bool:
    host = getattr(request.client, "host", "") or ""
    return host in _LOOPBACK


def _local_admin(request: Request) -> None:
    """Local console actions: loopback, or a device that may manage devices."""
    if _is_local(request):
        return
    device = current_device(request)
    if device is None:
        raise HTTPException(status_code=401, detail="Pair a device, or use the PC itself.")
    if "device:manage" not in device["scopes"]:
        raise HTTPException(status_code=403, detail="This device is not allowed to 'device:manage'.")


@router.get("/auth/status")
def auth_status() -> dict:
    svc = get_service()
    return {
        "require_auth": svc.store.require_auth(),
        "pairing_window_open": svc.codes.pending(),
        "paired_devices": len(svc.store.list_devices()),
        "device_kinds": sorted(DEVICE_KINDS),
    }


class IssueCodeBody(BaseModel):
    """Which kind of device this code is for. Default: the most restricted one."""

    kind: str = "android"


@router.post("/auth/pair/code")
def issue_pairing_code(request: Request, body: IssueCodeBody | None = None) -> dict:
    """Show a code on the PC that the device can type in. Local console only.

    The kind is fixed here, not chosen by the device redeeming the code: a code issued for a phone
    cannot be redeemed as a desktop, which would hand out `device:manage`.
    """
    _local_admin(request)
    service = get_service()
    requested_kind = (body.kind if body else "android") or "android"
    try:
        code = service.issue_code(requested_kind)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    service.store.log_event("pair_code_issued", None,
                            f"{requested_kind} from {getattr(request.client, 'host', '?')}"[:60])
    return {"code": code, "kind": requested_kind, "expires_in_s": int(service.codes.ttl_s),
            "note": f"Type this into the {requested_kind} device. Single use."}


@router.post("/auth/pair")
def pair(body: PairBody, request: Request) -> dict:
    service = get_service()
    try:
        result = service.enroll(body.code, body.name or "", body.kind,
                                client_key=getattr(request.client, "host", "?") or "?")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    device = result["device"]
    return {"device": device, "token": result["token"],
            "note": "Store this token on the device; it is not shown again."}


@router.get("/auth/me")
def me(request: Request) -> dict:
    device = current_device(request)
    if device is None:
        raise HTTPException(status_code=401, detail="A valid device token is required.")
    return {"id": device["id"], "name": device["name"], "kind": device["kind"],
            "scopes": sorted(device["scopes"]), "last_seen": device["last_seen"]}


@router.post("/auth/token/rotate")
def rotate_token(request: Request) -> dict:
    device = current_device(request)
    if device is None:
        raise HTTPException(status_code=401, detail="A valid device token is required.")
    try:
        return get_service().rotate(device, getattr(request.state, "raw_token", "") or "")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/devices")
def list_devices(_: dict = Depends(require_scope("device:read"))) -> dict:
    service = get_service()
    devices = [service._public(d) for d in service.store.list_devices()]
    return {"devices": devices, "count": len(devices)}


@router.patch("/devices/{device_id}")
def rename_device(device_id: str, body: RenameBody,
                  _: dict = Depends(require_scope("device:manage"))) -> dict:
    service = get_service()
    if not service.store.rename_device(device_id, body.name.strip()):
        raise HTTPException(status_code=404, detail="Unknown device.")
    return {"device": service._public(service.store.get_device(device_id))}


@router.delete("/devices/{device_id}")
def revoke_device(device_id: str, request: Request,
                  _: dict = Depends(require_scope("device:manage"))) -> dict:
    service = get_service()
    current = current_device(request)
    if current and current["id"] == device_id:
        raise HTTPException(status_code=409,
                            detail="Use another device to revoke this one.")
    if not service.revoke(device_id):
        raise HTTPException(status_code=404, detail="Unknown device.")
    return {"revoked": device_id}


@router.get("/security/events")
def security_events(limit: int = Query(100, ge=1, le=500),
                    _: dict = Depends(require_scope("device:manage"))) -> dict:
    return {"events": get_service().store.list_events(limit)}


@router.put("/security/settings")
def write_settings(body: SettingsBody, request: Request) -> dict:
    _local_admin(request)
    service = get_service()
    service.store.set_require_auth(body.require_auth)
    service.store.log_event("settings_changed", None, f"require_auth={body.require_auth}")
    return {"require_auth": service.store.require_auth()}
