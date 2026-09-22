"""Visitor uploads are private to their owner; existing shared libraries stay shared."""

import re


def workspace_owner(core, wid):
    row = core.db.one("SELECT owner FROM upload_sessions WHERE workspace_id=?", (wid,))
    return row["owner"] if row else None


def visible(core, principal, wid):
    owner = workspace_owner(core, wid)
    return principal.manages_data or owner is None or owner == principal.subject


def describe(core, principal, workspace):
    owner = workspace_owner(core, workspace["id"])
    return {**workspace, "can_manage": principal.manages_data or owner == principal.subject,
            "visibility": "private" if owner else "shared"}


def denied_status(core, principal, method, path):
    if principal.manages_data:
        return None
    upload = re.fullmatch(r"/api/rag/uploads/([a-f0-9]{32})(?:/.*)?", path)
    if upload:
        row = core.db.one("SELECT owner FROM upload_sessions WHERE id=?", (upload[1],))
        if not row or row["owner"] != principal.subject:
            return 404
    workspace = re.fullmatch(r"/api/rag/workspaces/([a-f0-9]{32})(.*)", path)
    if workspace:
        owner = workspace_owner(core, workspace[1])
        if owner and owner != principal.subject:
            return 404
        suffix = workspace[2]
        personal_write = ((not suffix and method in {"PATCH", "DELETE"})
                          or suffix == "/guide"
                          or (method == "POST" and suffix.startswith("/index-jobs")))
        if personal_write and owner != principal.subject:
            return 403
    return None
