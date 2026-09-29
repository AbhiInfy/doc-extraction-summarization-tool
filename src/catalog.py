from __future__ import annotations

import json
import re
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
    return discover_readiness_links(client=client, landing_url=landing_url, category=category)


def discover_readiness_links(
    client: HttpClient | None = None,
    landing_url: str = HCM_LANDING_URL,
    category: str | None = HUMAN_RESOURCES_CATEGORY,
) -> list[CatalogItem]:
    """Read the HCM readiness landing page and return What's New book links."""
    client = client or HttpClient()
    html = client.get(landing_url).text
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="book-data")
    if not script or not script.string:
        return []

    books = json.loads(script.string)
    items: list[CatalogItem] = []
    for book in books:
        book_category = book.get("category", "")
        if category and book_category != category:
            continue
        relative = book.get("html")
        if not relative:
            continue
        items.append(
            CatalogItem(
                title=book.get("title", "Untitled"),
                url=_absolute_book_url(relative, landing_url),
                category=book_category or category or "",
                description=book.get("description", ""),
            )
        )
    return items


MODULE_ALIASES = {
    "core hr": ("human resources",),
    "compensation": ("compensation",),
    "goals": ("talent management",),
    "performance management": ("talent management",),
    "recruiting": ("taleo enterprise", "taleo", "talent management"),
    "absence management": ("absence management",),
    "payroll": ("payroll",),
    "purchasing": ("procurement",),
    "supplier management": ("procurement",),
    "receivables": ("financials",),
    "payables": ("financials",),
    "cash management": ("financials",),
    "credit management": ("financials",),
    "collections": ("financials",),
    "general ledger": ("financials",),
    "assets": ("financials",),
    "intercompany": ("financials",),
    "expenses": ("financials",),
    "tax": ("financials",),
    "lease accounting": ("financials",),
    "revenue management": ("financials",),
    "inventory": ("inventory management",),
    "cost management": ("inventory management",),
    "product management": ("product lifecycle management",),
    "product information management": ("product lifecycle management",),
    "plm": ("product lifecycle management",),
    "pim": ("product lifecycle management",),
    "warehouse": ("warehouse management",),
    "wms": ("warehouse management",),
    "transportation": ("transportation management",),
    "otm": ("transportation management",),
    "global trade": ("global trade management",),
    "gtm": ("global trade management",),
    "s&op": ("sales and operations planning",),
    "sop": ("sales and operations planning",),
}

MODULE_SKIP = {
    "performance management": ("enterprise performance management",),
    "goals": ("enterprise performance management",),
}

FINANCE_MODULES = {
    "accounting hub",
    "assets",
    "cash management",
    "collections",
    "credit management",
    "expenses",
    "financials",
    "general ledger",
    "intercompany",
    "lease accounting",
    "payables",
    "receivables",
    "revenue management",
    "tax",
}

SCM_MODULES = {
    "cost management",
    "demand management",
    "global trade",
    "global trade management",
    "gtm",
    "inventory",
    "inventory management",
    "maintenance",
    "manufacturing",
    "order management",
    "otm",
    "pim",
    "plm",
    "product information management",
    "product lifecycle management",
    "product management",
    "s&op",
    "sales and operations planning",
    "sop",
    "supply chain collaboration",
    "supply planning",
    "transportation",
    "transportation management",
    "warehouse",
    "warehouse management",
    "wms",
}

HCM_MODULES = {
    "absence management",
    "compensation",
    "core hr",
    "goals",
    "payroll",
    "performance management",
    "recruiting",
}


def home_pillar(module_name: str) -> str | None:
    """Return HCM, Finance, or SCM when the Fusion module belongs to that family."""
    key = _normalize(module_name)
    aliases = MODULE_ALIASES.get(key, ())
    if key in FINANCE_MODULES or "financials" in aliases or "accounting hub" in aliases:
        return "Finance"
    if key in SCM_MODULES or any(token in SCM_MODULES for token in aliases):
        return "SCM"
    if key in HCM_MODULES or any(
        token in {"human resources", "talent management", "compensation", "payroll", "absence management"}
        for token in aliases
    ):
        return "HCM"
    return None


def match_module_name(module_name: str, catalog: list[CatalogItem]) -> CatalogItem | None:
    """Map a Fusion MODULE_NAME to the latest matching What's New book."""
    module_key = _normalize(module_name)
    needles = [module_key, *MODULE_ALIASES.get(module_key, ())]
    skipped = MODULE_SKIP.get(module_key, ())
    scored: list[tuple[int, str, CatalogItem]] = []
    for item in catalog:
        title = _normalize(item.title)
        if any(token in title for token in skipped):
            continue
        score = 0
        for needle in needles:
            if not needle:
                continue
            if needle == title:
                score = max(score, 300)
            elif title.startswith(f"{needle} ") or title.startswith(f"{needle} what's new"):
                score = max(score, 200)
            elif needle in title:
                score = max(score, 100)
        if score:
            scored.append((score, _release_key(item.title), item))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return scored[0][2]


def _release_key(title: str) -> str:
    match = re.search(r"(\d{2}[A-Za-z])\b", title)
    return match.group(1).upper() if match else ""


def resolve_human_resources_links(
    selections: list[str],
    catalog: list[CatalogItem] | None = None,
    client: HttpClient | None = None,
) -> list[CatalogItem]:
    """Resolve one or more What's New titles or URLs to catalog items."""
    catalog = catalog if catalog is not None else discover_readiness_links(client=client, category=None)
    if not catalog:
        raise ValueError("Could not load the What's New list from the readiness page.")

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
            "These What's New links were not found:\n"
            + "\n".join(f"  - {name}" for name in unknown)
            + "\nAvailable What's New links:\n"
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
