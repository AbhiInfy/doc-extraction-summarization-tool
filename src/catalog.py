from __future__ import annotations

import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http_client import HttpClient
from .models import CatalogItem

HCM_LANDING_URL = "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html"
READINESS_BASE = "https://docs.oracle.com/en/cloud/saas/readiness/"
HUMAN_RESOURCES_CATEGORY = "Human Resources"


def discover_human_resources_links(
    client: HttpClient | None = None,
    landing_url: str = HCM_LANDING_URL,
    category: str = HUMAN_RESOURCES_CATEGORY,
) -> list[CatalogItem]:
    """Read the HCM readiness landing page and return Human Resources book links."""
    client = client or HttpClient()
    html = client.get(landing_url).text
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="book-data")
    if not script or not script.string:
        return []

    books = json.loads(script.string)
    items: list[CatalogItem] = []
    for book in books:
        if book.get("category") != category:
            continue
        relative = book.get("html")
        if not relative:
            continue
        items.append(
            CatalogItem(
                title=book.get("title", "Untitled"),
                url=_absolute_book_url(relative, landing_url),
                category=book.get("category", category),
                description=book.get("description", ""),
            )
        )
    return items


def resolve_human_resources_links(
    selections: list[str],
    catalog: list[CatalogItem] | None = None,
    client: HttpClient | None = None,
) -> list[CatalogItem]:
    """Resolve one or more Human Resources titles or URLs to catalog items.

    Accepted values, for example:
    - Benefits What's New 26C
    - Human Resources What's New 26C
    - https://docs.oracle.com/en/cloud/saas/readiness/hcm/26c/hure-26c/index.html
    """
    catalog = catalog if catalog is not None else discover_human_resources_links(client=client)
    if not catalog:
        raise ValueError("Could not load the Human Resources list from the HCM readiness page.")

    resolved: list[CatalogItem] = []
    unknown: list[str] = []
    for raw in selections:
        value = raw.strip()
        if not value:
            continue
        match = _match_catalog_item(value, catalog)
        if match is None:
            unknown.append(value)
            continue
        if all(item.url != match.url for item in resolved):
            resolved.append(match)

    if unknown:
        available = "\n".join(f"  - {item.title}" for item in catalog)
        raise ValueError(
            "These Human Resources links were not found:\n"
            + "\n".join(f"  - {name}" for name in unknown)
            + "\nAvailable Human Resources links:\n"
            + available
        )
    return resolved


def _match_catalog_item(value: str, catalog: list[CatalogItem]) -> CatalogItem | None:
    normalized = _normalize(value)
    if value.startswith(("http://", "https://")):
        for item in catalog:
            if _normalize(item.url) == normalized or item.url.rstrip("/") == value.rstrip("/"):
                return item
        return CatalogItem(title=value, url=value, category=HUMAN_RESOURCES_CATEGORY)

    exact = [item for item in catalog if _normalize(item.title) == normalized]
    if len(exact) == 1:
        return exact[0]

    partial = [
        item
        for item in catalog
        if normalized in _normalize(item.title) or _normalize(item.title) in normalized
    ]
    if len(partial) == 1:
        return partial[0]
    return None


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("’", "'").split())


def _absolute_book_url(relative: str, landing_url: str) -> str:
    if relative.startswith(("http://", "https://")):
        return relative
    if relative.startswith("//"):
        return f"https:{relative}"
    if relative.startswith("../"):
        return urljoin(READINESS_BASE, relative.replace("../", "", 1))
    return urljoin(READINESS_BASE, relative)
