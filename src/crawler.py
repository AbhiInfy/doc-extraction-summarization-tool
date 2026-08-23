from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .extractor import extract_page
from .http_client import HttpClient
from .models import DocumentTree, TopicNode

ProgressCallback = Callable[[str, int, int], None]


def document_base_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if path.endswith(".html") or path.endswith(".htm") or path.endswith(".js"):
        path = path.rsplit("/", 1)[0] + "/"
    elif not path.endswith("/"):
        path += "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def load_document_tree(url: str, client: HttpClient | None = None) -> DocumentTree:
    client = client or HttpClient()
    base = document_base_url(url)
    toc_url = urljoin(base, "toc.js")
    raw = client.get(toc_url).text
    payload = _parse_toc_js(raw)
    toc_root = payload.get("toc") or []
    title = _document_title(url, client, toc_root)
    topics = _first_topic_list(toc_root)
    roots = [_build_node(item, base, depth=0) for item in topics]
    _assign_numbers(roots)
    return DocumentTree(source_url=url, title=title, roots=roots)


def crawl_tree(
    tree: DocumentTree,
    client: HttpClient | None = None,
    progress: ProgressCallback | None = None,
    include_images: bool = True,
) -> list[str]:
    client = client or HttpClient()
    nodes = [node for node in tree.walk() if node.url]
    errors: list[str] = []
    total = len(nodes)
    for index, node in enumerate(nodes, start=1):
        if progress:
            progress(node.title, index, total)
        try:
            html = client.get(node.url).text
            node.content = extract_page(html, node.url, fallback_title=node.title)
            if not include_images:
                node.content.blocks = [
                    block for block in node.content.blocks if block.kind != "image"
                ]
        except Exception as exc:  # noqa: BLE001 - keep crawl going for remaining topics
            node.error = str(exc)
            errors.append(f"{node.title}: {exc}")
    return errors


def _parse_toc_js(raw: str) -> dict:
    match = re.search(r"define\s*\(\s*(\{.*\})\s*\)\s*;?", raw, flags=re.DOTALL)
    if not match:
        raise ValueError("Could not parse toc.js. Confirm the URL is an Oracle What's New book.")
    return json.loads(match.group(1))


def _first_topic_list(toc_root: list) -> list[dict]:
    if not toc_root:
        return []
    first = toc_root[0]
    if isinstance(first, dict) and first.get("topics"):
        return first["topics"]
    return toc_root


def _document_title(url: str, client: HttpClient, toc_root: list) -> str:
    try:
        html = client.get(_index_url(url)).text
        soup = BeautifulSoup(html, "lxml")
        app_name = soup.find("meta", attrs={"name": "application-name"})
        if app_name and app_name.get("content"):
            return app_name["content"].strip()
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        if soup.title:
            return soup.title.get_text(" ", strip=True)
    except Exception:
        pass
    if toc_root and isinstance(toc_root[0], dict):
        return toc_root[0].get("heading") or "Oracle HCM Readiness"
    return "Oracle HCM Readiness"


def _index_url(url: str) -> str:
    if url.rstrip("/").endswith("index.html"):
        return url
    return urljoin(document_base_url(url), "index.html")


def _build_node(item: dict, base: str, depth: int) -> TopicNode:
    href = item.get("href")
    clean_href = href.split("#", 1)[0] if href else None
    url = urljoin(base, clean_href) if clean_href else None
    children = [_build_node(child, base, depth + 1) for child in item.get("topics") or []]
    return TopicNode(
        title=(item.get("title") or "Untitled").strip(),
        href=href,
        url=url,
        children=children,
        depth=depth,
    )


def _assign_numbers(nodes: list[TopicNode], prefix: str = "") -> None:
    for index, node in enumerate(nodes, start=1):
        node.number = f"{prefix}{index}" if not prefix else f"{prefix}.{index}"
        _assign_numbers(node.children, node.number)
