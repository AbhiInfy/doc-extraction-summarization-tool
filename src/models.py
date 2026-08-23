from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


BlockKind = Literal["heading", "paragraph", "list", "table", "image"]


@dataclass
class CatalogItem:
    title: str
    url: str
    category: str
    description: str = ""


@dataclass
class ContentBlock:
    kind: BlockKind
    text: str = ""
    level: int = 0
    items: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    image_url: str = ""
    caption: str = ""


@dataclass
class PageContent:
    title: str
    url: str
    blocks: list[ContentBlock] = field(default_factory=list)

    def plain_text(self, limit: int | None = None) -> str:
        parts = self._block_texts(self.blocks)
        text = "\n".join(part.strip() for part in parts if part and part.strip())
        if limit is not None:
            return text[:limit]
        return text

    def overview_text(self) -> str:
        before_heading: list[ContentBlock] = []
        for block in self.blocks:
            if block.kind == "heading":
                break
            before_heading.append(block)
        return "\n".join(self._block_texts(before_heading))

    def section_text(self, heading_part: str) -> str:
        capture = False
        collected: list[ContentBlock] = []
        needle = heading_part.lower()
        for block in self.blocks:
            if block.kind == "heading":
                if needle in block.text.lower():
                    capture = True
                    continue
                if capture:
                    break
            elif capture:
                collected.append(block)
        return "\n".join(self._block_texts(collected))

    @staticmethod
    def _block_texts(blocks: list[ContentBlock]) -> list[str]:
        parts: list[str] = []
        for block in blocks:
            if block.kind == "heading":
                parts.append(block.text)
            elif block.kind == "paragraph":
                parts.append(block.text)
            elif block.kind == "list":
                parts.extend(f"- {item}" for item in block.items)
            elif block.kind == "table":
                for row in block.rows:
                    parts.append(" | ".join(cell for cell in row if cell))
            elif block.kind == "image" and block.caption:
                parts.append(f"[Image] {block.caption}")
        return parts


@dataclass
class TopicNode:
    title: str
    href: str | None = None
    url: str | None = None
    children: list[TopicNode] = field(default_factory=list)
    number: str = ""
    depth: int = 0
    content: PageContent | None = None
    error: str | None = None

    def walk(self) -> list[TopicNode]:
        nodes = [self]
        for child in self.children:
            nodes.extend(child.walk())
        return nodes

    def leaf_count(self) -> int:
        if not self.children:
            return 1 if self.url else 0
        return sum(child.leaf_count() for child in self.children)


@dataclass
class DocumentTree:
    source_url: str
    title: str
    roots: list[TopicNode] = field(default_factory=list)

    def walk(self) -> list[TopicNode]:
        nodes: list[TopicNode] = []
        for root in self.roots:
            nodes.extend(root.walk())
        return nodes

    def numbered_index(self) -> list[tuple[str, str, int]]:
        return [(node.number, node.title, node.depth) for node in self.walk() if node.number]


@dataclass
class FeatureSummary:
    title: str
    number: str
    bullets: list[str]
    business_benefit: str = ""
    actions: list[str] = field(default_factory=list)
    whats_new: list[str] = field(default_factory=list)
    client_impact: str = ""
    enablement: str = ""
    talking_points: list[str] = field(default_factory=list)
    theme: str = ""
    section: str = ""


@dataclass
class CategorySummary:
    title: str
    features: list[FeatureSummary] = field(default_factory=list)


@dataclass
class ThemeSummary:
    title: str
    message: str
    features: list[str] = field(default_factory=list)


@dataclass
class DocumentSummary:
    title: str
    source_url: str
    executive_summary: list[str]
    highlights: list[str]
    actions: list[str]
    categories: list[CategorySummary]
    topic_count: int
    used_ai: bool = False
    product_name: str = ""
    release: str = ""
    audience_line: str = ""
    why_it_matters: list[str] = field(default_factory=list)
    snapshot: list[tuple[str, str]] = field(default_factory=list)
    themes: list[ThemeSummary] = field(default_factory=list)
    discussion_points: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    features: list[FeatureSummary] = field(default_factory=list)


@dataclass
class GenerationResult:
    source_url: str
    title: str
    topic_count: int
    docx_path: Path
    pptx_path: Path
    used_ai: bool
    errors: list[str] = field(default_factory=list)
