import re
from urllib.parse import unquote, urlparse

_REPOSITORY = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?![A-Za-z0-9_.-])")


def description_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (description_text(item) for item in value)))
    if isinstance(value, dict):
        current = value.get("text", "")
        attrs = value.get("attrs") or {}
        link = attrs.get("href") or attrs.get("url") or ""
        marked_links = " ".join(
            (mark.get("attrs") or {}).get("href", "")
            for mark in value.get("marks", [])
            if mark.get("type") == "link"
        )
        children = description_text(value.get("content", []))
        return " ".join(part for part in (current, link, marked_links, children) if part)
    return ""


def repository_candidates(description, organization="RogersCommunications"):
    text = description_text(description)
    candidates = set()
    for match in re.finditer(r"https?://(?:www\.)?github\.com/([^\s)\]>\"']+)", text, re.IGNORECASE):
        path = unquote(urlparse(match.group(0).rstrip(".,;:" )).path)
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0].casefold() == organization.casefold():
            candidates.add(f"{organization}/{parts[1].removesuffix(".git")}")
    for owner, name in _REPOSITORY.findall(text):
        if owner.casefold() == organization.casefold() and name.casefold() != "repositories":
            candidates.add(f"{organization}/{name.removesuffix(".git")}")
    return sorted(candidates, key=str.casefold)


def normalize_issue(issue, organization="RogersCommunications"):
    fields = issue.get("fields") or {}
    description = description_text(fields.get("description"))
    return {
        "key": issue.get("key", ""),
        "summary": fields.get("summary", ""),
        "description": description,
        "status": (fields.get("status") or {}).get("name", "Unknown"),
        "issue_type": (fields.get("issuetype") or {}).get("name", "Issue"),
        "updated": fields.get("updated"),
        "project": (fields.get("project") or {}).get("key"),
        "repository_candidates": repository_candidates(description, organization),
    }