from __future__ import annotations

import json
import os
import re
from collections import defaultdict

import requests

from .models import (
    CategorySummary,
    DocumentSummary,
    DocumentTree,
    FeatureSummary,
    ThemeSummary,
    TopicNode,
)

SKIP_TITLES = {
    "title and copyright information",
    "revision history",
    "overview",
    "feature summary",
}

THEME_RULES = (
    ("Redwood experience", r"\bredwood\b"),
    ("AI assistance", r"\b(ai|agent|agents|generative|assistant|llm)\b"),
    ("Documents and certifications", r"\b(certif\w*|documents?|attachments?)\b"),
    ("Enrollment experience", r"\b(enroll\w*|life event|alerts?)\b"),
    ("Administrator productivity", r"\b(simulat\w*|administrat\w*)\b"),
    ("Configuration and extensibility", r"\b(configur\w*|page properties|profile option|rules?)\b"),
)


def summarize_document(tree: DocumentTree, use_ai: bool = True) -> DocumentSummary:
    categories = _category_summaries(tree)
    features = [
        feature
        for category in categories
        for feature in category.features
        if _is_client_feature(feature)
    ]
    briefing = _client_briefing(tree, categories, features)
    if use_ai:
        try:
            briefing = _enrich_with_ai(tree, briefing)
        except Exception:
            briefing.used_ai = False
    return briefing


def _category_summaries(tree: DocumentTree) -> list[CategorySummary]:
    categories: list[CategorySummary] = []
    for root in tree.roots:
        if root.children:
            _collect_categories(root, categories)
        elif root.url and _usable_title(root.title):
            categories.append(
                CategorySummary(title=root.title, features=[_feature_from_node(root, root.title)])
            )
    return categories


def _collect_categories(node: TopicNode, categories: list[CategorySummary]) -> None:
    child_features = [
        _feature_from_node(child, node.title)
        for child in node.children
        if child.url and not child.children and _usable_title(child.title)
    ]
    if child_features:
        categories.append(
            CategorySummary(
                title=f"{node.number} {node.title}".strip(),
                features=child_features,
            )
        )
    for child in node.children:
        if child.children:
            _collect_categories(child, categories)


def _feature_from_node(node: TopicNode, section: str) -> FeatureSummary:
    content = node.content
    text = content.plain_text() if content else ""
    overview = content.overview_text() if content else ""
    steps = content.section_text("steps to enable") if content else ""
    tips = content.section_text("tips and considerations") if content else ""
    benefit = _business_benefit(content, text) if content else _sentence_with(text, "business benefit")
    whats_new = _whats_new(overview or text)
    enablement = _enablement(steps, text)
    actions = _action_lines(steps or text)
    talking = _talking_points(benefit, tips, whats_new)
    return FeatureSummary(
        title=node.title,
        number=node.number,
        bullets=whats_new[:3],
        business_benefit=benefit,
        actions=actions[:3],
        whats_new=whats_new[:4],
        client_impact=benefit or (whats_new[0] if whats_new else ""),
        enablement=enablement,
        talking_points=talking,
        theme=_classify_theme(node.title, text),
        section=section,
    )


def _client_briefing(
    tree: DocumentTree,
    categories: list[CategorySummary],
    features: list[FeatureSummary],
) -> DocumentSummary:
    product, release = _product_release(tree.title)
    themes = _themes(features)
    auto = sum(1 for feature in features if feature.enablement.lower().startswith("auto"))
    opt_in = sum(1 for feature in features if "opt" in feature.enablement.lower() or "profile" in feature.enablement.lower())
    setup = len(features) - auto - opt_in
    snapshot = [
        (str(len(features)), "Client-facing features"),
        (str(len(themes) or 1), "Themes to discuss"),
        (str(opt_in), "Opt-in / profile option"),
        (str(setup), "Setup or decision needed"),
    ]
    why = _why_it_matters(product, features, themes)
    highlights = []
    for feature in features:
        line = feature.business_benefit or (feature.whats_new[0] if feature.whats_new else "")
        if line:
            highlights.append(f"{feature.title}: {_short(line, 140)}")
        if len(highlights) >= 8:
            break
    actions = _prioritized_actions(features)
    executive = [
        f"{tree.title} is a client readiness briefing covering {len(features)} features in {product}{' ' + release if release else ''}.",
        f"The release is organized around {', '.join(theme.title for theme in themes[:3]) or 'product enhancements'}.",
        f"{auto} feature(s) look auto-enabled; {opt_in} need opt-in or a profile option; {setup} need setup or a client decision before users see value.",
        "Use this deck in the client workshop to agree impact, owners, and the enablement sequence. Full setup detail remains in the Word document.",
    ]
    return DocumentSummary(
        title=tree.title,
        source_url=tree.source_url,
        executive_summary=executive,
        highlights=highlights,
        actions=actions,
        categories=categories,
        topic_count=sum(1 for node in tree.walk() if node.url),
        used_ai=False,
        product_name=product,
        release=release,
        audience_line="Prepared for a client project workshop: functional owners, HRIS, and implementation partners.",
        why_it_matters=why,
        snapshot=snapshot,
        themes=themes,
        discussion_points=_discussion_points(product, features),
        next_steps=_next_steps(product),
        features=features,
    )


def _enrich_with_ai(tree: DocumentTree, briefing: DocumentSummary) -> DocumentSummary:
    payload = {
        "title": tree.title,
        "product": briefing.product_name,
        "release": briefing.release,
        "features": [
            {
                "title": feature.title,
                "number": feature.number,
                "section": feature.section,
                "theme": feature.theme,
                "whats_new": feature.whats_new,
                "business_benefit": feature.business_benefit,
                "enablement": feature.enablement,
                "actions": feature.actions,
            }
            for feature in briefing.features
        ],
    }
    prompt = (
        "Provide a PowerPoint summary so we can present this Oracle HCM readiness "
        f"release to a client. Focus on {briefing.product_name} {briefing.release} "
        "as a consultative client briefing, not a documentation dump.\n\n"
        "Audience: client HR, Benefits/HRIS, and implementation stakeholders.\n"
        "Tone: clear, business-first, suitable to speak aloud in a meeting.\n"
        "Do not invent features that are not in the source JSON.\n\n"
        "Return JSON with:\n"
        "- audience_line: one sentence\n"
        "- executive_summary: 4 short spoken talking points\n"
        "- why_it_matters: 4 business outcomes for the client\n"
        "- themes: array of {title, message, features}\n"
        "- highlights: up to 8 one-line takeaways\n"
        "- features: array matching source titles, each with "
        "{title, whats_new (2-3 short bullets), business_benefit, client_impact, "
        "enablement, talking_points (2), actions (1-2)}\n"
        "- actions: up to 8 prioritized client actions\n"
        "- discussion_points: 5 workshop questions\n"
        "- next_steps: 4 recommended next steps\n\n"
        f"SOURCE:\n{json.dumps(payload)[:22000]}"
    )
    data = None
    try:
        data = _call_claude(prompt)
    except Exception:
        data = None
    if data is None:
        try:
            data = _call_openai(prompt)
        except Exception:
            data = None
    if not data:
        return briefing
    briefing.audience_line = str(data.get("audience_line") or briefing.audience_line)
    briefing.executive_summary = _as_list(data.get("executive_summary")) or briefing.executive_summary
    briefing.why_it_matters = _as_list(data.get("why_it_matters")) or briefing.why_it_matters
    briefing.highlights = _as_list(data.get("highlights")) or briefing.highlights
    briefing.actions = _as_list(data.get("actions")) or briefing.actions
    briefing.discussion_points = _as_list(data.get("discussion_points")) or briefing.discussion_points
    briefing.next_steps = _as_list(data.get("next_steps")) or briefing.next_steps
    if isinstance(data.get("themes"), list) and data["themes"]:
        briefing.themes = [
            ThemeSummary(
                title=str(item.get("title", "Theme")),
                message=str(item.get("message", "")),
                features=_as_list(item.get("features")),
            )
            for item in data["themes"]
            if isinstance(item, dict)
        ]
    by_title = {_normalize(feature.title): feature for feature in briefing.features}
    for item in data.get("features") or []:
        if not isinstance(item, dict):
            continue
        feature = by_title.get(_normalize(str(item.get("title", ""))))
        if not feature:
            continue
        feature.whats_new = _as_list(item.get("whats_new")) or feature.whats_new
        feature.bullets = feature.whats_new[:3]
        feature.business_benefit = str(item.get("business_benefit") or feature.business_benefit)
        feature.client_impact = str(item.get("client_impact") or feature.client_impact)
        feature.enablement = str(item.get("enablement") or feature.enablement)
        feature.talking_points = _as_list(item.get("talking_points")) or feature.talking_points
        feature.actions = _as_list(item.get("actions")) or feature.actions
    briefing.used_ai = True
    return briefing


def _call_claude(prompt: str) -> dict | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 8000,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt + "\n\nReturn only valid JSON."}],
        },
        timeout=90,
    )
    response.raise_for_status()
    content = response.json()["content"][0]["text"]
    return _parse_json(content)


def _call_openai(prompt: str) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You write client-ready Oracle HCM PowerPoint briefings. Return JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return _parse_json(response.choices[0].message.content or "")


def _themes(features: list[FeatureSummary]) -> list[ThemeSummary]:
    grouped: dict[str, list[FeatureSummary]] = defaultdict(list)
    for feature in features:
        grouped[feature.theme or "Product enhancements"].append(feature)
    messages = {
        "AI assistance": "New or enhanced agents that reduce manual Benefits/HR inquiry work.",
        "Redwood experience": "Modern pages the client should plan for in training and change management.",
        "Documents and certifications": "Faster evidence collection and fewer follow-ups during life events.",
        "Enrollment experience": "Clearer employee communications and fewer enrollment exceptions.",
        "Administrator productivity": "Tools that let Benefits admins test, simulate, and resolve work faster.",
        "Configuration and extensibility": "Setup choices that control what users see after go-live.",
        "Product enhancements": "Functional improvements to review for process and control impact.",
    }
    themes = []
    for title, items in grouped.items():
        themes.append(
            ThemeSummary(
                title=title,
                message=messages.get(title, messages["Product enhancements"]),
                features=[item.title for item in items],
            )
        )
    themes.sort(key=lambda item: len(item.features), reverse=True)
    return themes


def _why_it_matters(product: str, features: list[FeatureSummary], themes: list[ThemeSummary]) -> list[str]:
    points = [
        f"{product} changes in this update affect employee experience, administrator workload, and go-live setup.",
    ]
    if any(theme.title == "Redwood experience" for theme in themes):
        points.append("Redwood pages change how administrators and employees work day to day, so training and communications should be planned.")
    if any(theme.title == "AI assistance" for theme in themes):
        points.append("AI agents can deflect routine questions, but the client should agree scope, security, and who owns the prompt/configuration.")
    if any("certif" in feature.title.lower() or "document" in feature.title.lower() for feature in features):
        points.append("Certification and document updates reduce back-and-forth during life events if the client adopts the new upload and preview options.")
    points.append("A short enablement review is needed so auto-enabled features are accepted and opt-in features are scheduled.")
    return points[:4]


def _discussion_points(product: str, features: list[FeatureSummary]) -> list[str]:
    return [
        f"Which {product} features should be in scope for this client update?",
        "Which items are auto-enabled and need only communication, versus opt-in work?",
        "Who owns Benefits/HR configuration, testing, and employee messaging?",
        "Are there policy, security, or union constraints on AI or document handling?",
        "What is the target date to confirm setup, UAT, and change-management materials?",
    ]


def _next_steps(product: str) -> list[str]:
    return [
        f"Walk through the {product} feature slides and mark each as Adopt / Defer / Not applicable.",
        "Assign a functional owner and target date for every setup or opt-in item.",
        "Confirm test scenarios for Redwood pages, documents/certifications, and any AI agent.",
        "Use the Word document for detailed enablement steps after the workshop.",
    ]


def _prioritized_actions(features: list[FeatureSummary]) -> list[str]:
    actions = []
    for feature in features:
        if feature.enablement.lower().startswith("auto"):
            actions.append(f"{feature.title}: confirm auto-enablement and add to the client comms plan.")
        elif feature.actions:
            actions.append(f"{feature.title}: { _short(feature.actions[0], 120)}")
        else:
            actions.append(f"{feature.title}: review enablement and decide adopt or defer.")
        if len(actions) >= 8:
            break
    return actions


def _whats_new(text: str) -> list[str]:
    bullets = []
    for raw in text.splitlines():
        line = raw.strip(" -*\t")
        if 20 < len(line) < 220 and not line.lower().startswith(("business benefit", "note:", "previous", "next")):
            bullets.append(line)
        if len(bullets) >= 4:
            return bullets
    return _lead_sentences(text, limit=3)


def _business_benefit(content, text: str) -> str:
    from_heading = content.section_text("business benefit") if content else ""
    if from_heading:
        return _short(re.sub(r"(?i)^business benefit:\s*", "", from_heading), 280)
    labeled = _sentence_with(text, "business benefit")
    if labeled:
        return _short(re.sub(r"(?i)^business benefit:\s*", "", labeled), 280)
    return _short(_lead_sentences(text, limit=1)[0], 280) if _lead_sentences(text, limit=1) else ""


def _enablement(steps: str, full_text: str) -> str:
    blob = f"{steps}\n{full_text}".lower()
    if any(token in blob for token in ("no steps to enable", "automatically available", "nothing to do", "enabled by default", "no setup required")):
        return "Auto-enabled"
    if "profile option" in blob or "opt in" in blob or "opt-in" in blob:
        return "Opt-in / profile option"
    if steps.strip():
        return "Setup required"
    return "Review recommended"


def _talking_points(benefit: str, tips: str, whats_new: list[str]) -> list[str]:
    points = []
    if benefit:
        points.append(_short(benefit, 160))
    for raw in tips.splitlines():
        line = raw.strip(" -*\t")
        if len(line) > 30:
            points.append(_short(line, 160))
        if len(points) >= 3:
            break
    for item in whats_new:
        if item not in points:
            points.append(_short(item, 160))
        if len(points) >= 3:
            break
    return points[:3]


def _classify_theme(title: str, text: str) -> str:
    title_l = title.lower()
    for theme, pattern in THEME_RULES:
        if re.search(pattern, title_l):
            return theme
    blob = f"{title} {text}".lower()
    for theme, pattern in THEME_RULES:
        if re.search(pattern, blob):
            return theme
    return "Product enhancements"


def _product_release(title: str) -> tuple[str, str]:
    match = re.search(r"\b(\d{2}[A-Da-d])\b", title)
    release = match.group(1).upper() if match else ""
    product = re.sub(r"Oracle Fusion Cloud\s*", "", title, flags=re.I)
    product = re.sub(r"What's New.*", "", product, flags=re.I)
    if release:
        product = product.replace(release, "")
    product = product.strip(" -–")
    return product or "HCM", release


def _is_client_feature(feature: FeatureSummary) -> bool:
    return _usable_title(feature.title) and bool(feature.whats_new or feature.business_benefit or feature.actions)


def _usable_title(title: str) -> bool:
    return title.strip().lower() not in SKIP_TITLES


def _lead_sentences(text: str, limit: int = 3) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    useful = []
    for part in re.split(r"(?<=[.!?])\s+", cleaned):
        if len(part) < 40 or part.lower().startswith(("previous", "next", "javascript")):
            continue
        useful.append(part.strip())
        if len(useful) >= limit:
            break
    return useful


def _sentence_with(text: str, needle: str) -> str:
    index = text.lower().find(needle)
    if index < 0:
        return ""
    return _short(re.split(r"(?<=[.!?])\s+", text[index:], maxsplit=1)[0], 280)


def _action_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip(" -*\t")
        if len(line) > 20:
            lines.append(line)
        if len(lines) >= 4:
            break
    return lines


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).removesuffix("```").strip()
    return json.loads(raw)


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _short(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"
