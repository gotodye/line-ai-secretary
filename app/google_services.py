"""Google Calendar / Gmail / Drive / Tasks / Sheets service wrappers."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build

from app.google_oauth import get_credentials

TW = timezone(timedelta(hours=8))


def _svc(user_id: str, name: str, version: str):
    return build(name, version, credentials=get_credentials(user_id), cache_discovery=False)


# ---- Calendar ----

def list_upcoming_events(user_id: str, max_results: int = 8) -> list[dict[str, Any]]:
    service = _svc(user_id, "calendar", "v3")
    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = []
    for item in result.get("items", []):
        start = item["start"].get("dateTime") or item["start"].get("date")
        events.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary", "(無標題)"),
                "start": start,
                "end": item["end"].get("dateTime") or item["end"].get("date"),
                "location": item.get("location"),
                "htmlLink": item.get("htmlLink"),
            }
        )
    return events


def create_event(
    user_id: str,
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
) -> dict[str, Any]:
    service = _svc(user_id, "calendar", "v3")
    body: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start_iso, "timeZone": "Asia/Taipei"},
        "end": {"dateTime": end_iso, "timeZone": "Asia/Taipei"},
    }
    created = service.events().insert(calendarId="primary", body=body).execute()
    return {
        "id": created.get("id"),
        "summary": created.get("summary"),
        "start": created["start"].get("dateTime") or created["start"].get("date"),
        "htmlLink": created.get("htmlLink"),
    }


# ---- Gmail ----

def list_recent_emails(user_id: str, max_results: int = 5, query: str = "in:inbox") -> list[dict]:
    service = _svc(user_id, "gmail", "v1")
    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    out = []
    for meta in listed.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=meta["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        out.append(
            {
                "id": msg["id"],
                "snippet": msg.get("snippet", ""),
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", "(無主旨)"),
                "date": headers.get("Date", ""),
            }
        )
    return out


def send_email(user_id: str, to: str, subject: str, body: str) -> dict:
    service = _svc(user_id, "gmail", "v1")
    message = MIMEText(body, _charset="utf-8")
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"id": sent.get("id"), "to": to, "subject": subject}


# ---- Drive ----

def search_drive(user_id: str, query: str, max_results: int = 8) -> list[dict]:
    service = _svc(user_id, "drive", "v3")
    # Escape single quotes in query for Drive q language
    safe = query.replace("'", "\\'")
    q = f"fullText contains '{safe}' and trashed = false"
    result = (
        service.files()
        .list(
            q=q,
            pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime, webViewLink)",
            orderBy="modifiedTime desc",
        )
        .execute()
    )
    return result.get("files", [])


def list_recent_drive_files(user_id: str, max_results: int = 8) -> list[dict]:
    service = _svc(user_id, "drive", "v3")
    result = (
        service.files()
        .list(
            pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime, webViewLink)",
            orderBy="modifiedTime desc",
            q="trashed = false",
        )
        .execute()
    )
    return result.get("files", [])


# ---- Tasks ----

def list_tasks(user_id: str, max_results: int = 15) -> list[dict]:
    service = _svc(user_id, "tasks", "v1")
    lists = service.tasklists().list(maxResults=1).execute().get("items", [])
    if not lists:
        return []
    tasklist_id = lists[0]["id"]
    tasks = (
        service.tasks()
        .list(tasklist=tasklist_id, maxResults=max_results, showCompleted=False)
        .execute()
        .get("items", [])
    )
    return [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "due": t.get("due"),
            "notes": t.get("notes"),
            "status": t.get("status"),
        }
        for t in tasks
    ]


def create_task(user_id: str, title: str, notes: str = "", due_iso: str | None = None) -> dict:
    service = _svc(user_id, "tasks", "v1")
    lists = service.tasklists().list(maxResults=1).execute().get("items", [])
    if not lists:
        created_list = service.tasklists().insert(body={"title": "My Tasks"}).execute()
        tasklist_id = created_list["id"]
    else:
        tasklist_id = lists[0]["id"]
    body: dict[str, Any] = {"title": title, "notes": notes}
    if due_iso:
        body["due"] = due_iso
    task = service.tasks().insert(tasklist=tasklist_id, body=body).execute()
    return {"id": task.get("id"), "title": task.get("title"), "due": task.get("due")}


# ---- Sheets (read range) ----

def read_sheet(user_id: str, spreadsheet_id: str, range_a1: str) -> dict:
    service = _svc(user_id, "sheets", "v4")
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_a1)
        .execute()
    )
    return {"range": result.get("range"), "values": result.get("values", [])}
