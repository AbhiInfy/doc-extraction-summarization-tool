from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import ContentBlock, PageContent


def extract_page(html: str, url: str, fallback_title: str = "") -> PageContent:
    soup = BeautifulSoup(html, "lxml")
    title = _page_title(soup, fallback_title)
    section = soup.select_one("article#globalBody section") or soup.select_one("main") or soup.body
    if section is None:
        return PageContent(title=title, url=url)

    for junk in section.select(".noscript, #copyright, script, style"):
        junk.decompose()

    blocks: list[ContentBlock] = []
    for child in section.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "header":
            continue
        blocks.extend(_blocks_from_element(child, url))

    return PageContent(title=title, url=url, blocks=_merge_adjacent_lists(blocks))


def _page_title(soup: BeautifulSoup, fallback_title: str) -> str:
    heading = soup.select_one("h1.fa-chapter, h1")
    if heading:
        return _clean(heading.get_text(" ", strip=True))
    if soup.title:
        return _clean(soup.title.get_text(" ", strip=True))
    return fallback_title or "Untitled"


def _blocks_from_element(element: Tag, page_url: str) -> list[ContentBlock]:
    name = element.name or ""
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        text = _clean(element.get_text(" ", strip=True))
        if not text:
            return []
        return [ContentBlock(kind="heading", text=text, level=int(name[1]))]

    if name in {"ul", "ol"}:
        items = [_clean(li.get_text(" ", strip=True)) for li in element.find_all("li", recursive=False)]
        items = [item for item in items if item]
        return [ContentBlock(kind="list", items=items)] if items else []

    if name == "table":
        rows = _table_rows(element)
        return [ContentBlock(kind="table", rows=rows)] if rows else []

    if name == "img":
        return _image_block(element, page_url)

    if name in {"p", "div", "blockquote"}:
        image = element.find("img")
        if image:
            blocks = _image_block(image, page_url)
            caption = element.get("class") or []
            if "titleinfigure" in caption:
                text = _clean(element.get_text(" ", strip=True))
                if blocks and text:
                    blocks[0].caption = text
            return blocks

        text = _clean(element.get_text(" ", strip=True))
        if not text:
            return []
        if "titleinfigure" in (element.get("class") or []):
            return [ContentBlock(kind="image", caption=text)]
        return [ContentBlock(kind="paragraph", text=text)]

    blocks: list[ContentBlock] = []
    for child in element.children:
        if isinstance(child, Tag):
            blocks.extend(_blocks_from_element(child, page_url))
    return blocks


def _image_block(image: Tag, page_url: str) -> list[ContentBlock]:
    src = image.get("src")
    if not src or src.startswith("data:"):
        return []
    return [
        ContentBlock(
            kind="image",
            image_url=urljoin(page_url, src),
            caption=_clean(image.get("alt") or ""),
        )
    ]


def _table_rows(table: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def _merge_adjacent_lists(blocks: list[ContentBlock]) -> list[ContentBlock]:
    merged: list[ContentBlock] = []
    for block in blocks:
        if (
            merged
            and block.kind == "list"
            and merged[-1].kind == "list"
        ):
            merged[-1].items.extend(block.items)
            continue
        if merged and block.kind == "image" and merged[-1].kind == "image":
            previous = merged[-1]
            if block.image_url and not previous.image_url:
                previous.image_url = block.image_url
            if block.caption and not previous.caption:
                previous.caption = block.caption
            if not block.image_url:
                continue
        merged.append(block)
    return merged


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", text).strip()
