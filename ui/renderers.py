"""HTML and Markdown renderers for slide previews, deck views, and outlines."""

from typing import Optional
from schemas.layouts import STATUS_ICONS, LAYOUT_ICONS, AVAILABLE_LAYOUTS
from utils.state import deck_state


def format_slide_preview(slide: dict) -> str:
    """Render a single slide as Markdown for the slide-level editing tab."""
    lines: list[str] = []
    lines.append(f"**שקף {slide.get('slide_num')}:** {slide.get('slide_description', '')}")
    lines.append(f"**סטטוס:** {slide.get('generation_status', 'ממתין')}")
    lines.append("")
    for obj in slide.get("slide_objects", []):
        obj_id: str = obj.get("object_id", "?")
        obj_name: str = obj.get("object_name", "?")
        status: str = obj.get("validation_status", "לא נוצר")
        content: str = obj.get("generated_content", "")
        icon: str = STATUS_ICONS.get(status, "⏳")
        lines.append("---")
        lines.append(f"{icon} **{obj_id}** — {obj_name}")
        lines.append(f"סטטוס: {status}")
        lines.append("תוכן:")
        lines.append(f"```\n{content or '(ריק)'}\n```")
    return "\n".join(lines)


def render_slide_html(slide: dict, slide_index: int, total_slides: int) -> str:
    """Render a single slide as an HTML card for the deck preview."""
    slide_num = slide.get("slide_num", "?")
    layout: str = slide.get("slide_layout", "title_bullets")
    title_text, body_parts = _extract_slide_parts(slide)

    if not title_text:
        title_text = slide.get("slide_description", "")

    body_html: str = _assemble_body_html(layout, body_parts)

    if layout == "section_header":
        return _render_section_header(title_text, slide_num, total_slides)

    return f'''
    <div class="slide-card">
        <div class="slide-title-bar">{title_text}</div>
        <div class="slide-body">{body_html}</div>
        <div class="slide-footer">שקף {slide_num} מתוך {total_slides}</div>
    </div>'''


def _extract_slide_parts(slide: dict) -> tuple[str, list[str]]:
    """Walk slide objects and separate the title text from body HTML parts."""
    title_text: str = ""
    body_parts: list[str] = []

    for obj in slide.get("slide_objects", []):
        obj_name: str = obj.get("object_name", "").lower()
        obj_id: str = obj.get("object_id", "")
        content: str = obj.get("generated_content", "")
        status: str = obj.get("validation_status", "")
        if not content:
            continue

        if "כותרת" in obj_name or "תת" in obj_name:
            title_text = content
        else:
            icon: str = STATUS_ICONS.get(status, "⏳")
            if obj_id == "Key Statement":
                body_parts.append(f'<div class="slide-key-statement">{content}</div>')
            elif obj_id in ("Content Right", "Content Left"):
                col_class: str = "slide-col-right" if obj_id == "Content Right" else "slide-col-left"
                col_label: str = obj.get("object_name", "")
                body_parts.append(_render_content_block(content, icon, col_label, col_class))
            else:
                body_parts.append(_render_content_block(content, icon, obj.get("object_name", "")))

    return title_text, body_parts


def _assemble_body_html(layout: str, body_parts: list[str]) -> str:
    """Combine body parts into final HTML based on the slide layout."""
    if layout == "title_two_columns" and any("slide-col-" in p for p in body_parts):
        return f'<div class="slide-two-columns">{"".join(body_parts)}</div>'
    if body_parts:
        return "\n".join(body_parts)
    if layout in ("title_only", "section_header"):
        return ""
    return '<p class="slide-empty">אין תוכן</p>'


def _render_section_header(title_text: str, slide_num, total_slides: int) -> str:
    """Render a section-header slide card."""
    return f'''
    <div class="slide-card slide-section-header">
        <div class="slide-section-title">{title_text}</div>
        <div class="slide-footer">שקף {slide_num} מתוך {total_slides}</div>
    </div>'''


def _render_content_block(
    content: str, icon: str, label: str, wrapper_class: Optional[str] = None
) -> str:
    """Render a content block as either a bullet list or paragraph."""
    is_bullets: bool = _detect_bullets(content)

    if is_bullets:
        items_html: str = _build_bullet_items(content)
        inner = f'<div class="slide-obj-label">{icon} {label}</div><ul class="slide-bullets">{items_html}</ul>'
    else:
        inner = f'<div class="slide-obj-label">{icon} {label}</div><p class="slide-text">{content}</p>'

    if wrapper_class:
        label_class: str = "slide-col-label" if "col" in wrapper_class else "slide-obj-label"
        if is_bullets:
            inner = f'<div class="{label_class}">{icon} {label}</div><ul class="slide-bullets">{items_html}</ul>'
        else:
            inner = f'<div class="{label_class}">{icon} {label}</div><p class="slide-text">{content}</p>'
        return f'<div class="{wrapper_class}">{inner}</div>'
    return inner


def _detect_bullets(content: str) -> bool:
    """Check whether content looks like a bullet list."""
    return "\n" in content and any(
        line.strip().startswith(("-", "•", "–")) for line in content.split("\n")
    )


def _build_bullet_items(content: str) -> str:
    """Convert raw bullet-list text into <li> HTML items."""
    items: str = ""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith(("-", "•", "–")):
            line = line.lstrip("-•– ").strip()
        if line:
            items += f"<li>{line}</li>"
    return items


#  Deck Preview

def render_deck_preview(skeleton: Optional[dict] = None) -> str:
    """Render the full deck as a scrollable HTML preview."""
    if skeleton is None:
        skeleton = deck_state.get("skeleton")
    if skeleton is None:
        return '<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>'
    slides: list[dict] = skeleton.get("slides", [])
    total: int = len(slides)
    slides_html: str = "\n".join(render_slide_html(slide, i, total) for i, slide in enumerate(slides))
    return f'''
    <div class="deck-preview">
        <div class="preview-header">📊 תצוגה מקדימה — {total} שקפים</div>
        <div class="slides-container">{slides_html}</div>
    </div>'''


#  Outline Preview

def render_outline_html(outline: dict) -> str:
    """Render a proposed outline as HTML preview for user approval."""
    slides: list[dict] = outline.get("slides", [])
    total: int = len(slides)

    with_content: int = sum(1 for s in slides if s.get("has_content", True))
    without_content: int = total - with_content

    warning_html: str = ""
    if without_content > 0:
        warning_html = f'<div class="outline-warning">⚠️ {without_content} שקפים מסומנים כחסרי מידע מספיק</div>'

    slides_html: str = ""
    for slide in slides:
        slides_html += _render_outline_slide_card(slide)

    return f'''
    <div class="outline-preview">
        <div class="outline-header">📋 מבנה מוצע — {total} שקפים</div>
        {warning_html}
        <div class="outline-cards">{slides_html}</div>
    </div>'''


def _render_outline_slide_card(slide: dict) -> str:
    """Render a single slide card inside the outline preview."""
    slide_num = slide.get("slide_num", "?")
    title: str = slide.get("title", "ללא כותרת")
    layout: str = slide.get("layout", "title_bullets")
    topics = slide.get("topics", [])
    has_content: bool = slide.get("has_content", True)

    content_icon: str = "✅" if has_content else "⚠️"
    card_class: str = "outline-card" if has_content else "outline-card outline-card-warning"
    layout_icon: str = LAYOUT_ICONS.get(layout, "📋")
    layout_label: str = AVAILABLE_LAYOUTS.get(layout, layout)

    content_html: str = _render_outline_content(layout, title, topics)

    return f'''
    <div class="{card_class}">
        <div class="outline-card-header">
            <span class="outline-num">{slide_num}</span>
            <span class="outline-title">{title}</span>
            <span class="outline-content-icon">{content_icon}</span>
        </div>
        <div class="outline-layout-badge">{layout_icon} {layout_label}</div>
        {content_html}
    </div>'''


def _render_outline_content(layout: str, title: str, topics) -> str:
    """Render the content section of an outline card based on layout type."""
    if layout in ("title_only", "section_header"):
        return '<p class="outline-placeholder">שקף כותרת בלבד</p>'

    if layout == "title_two_columns":
        return _render_outline_two_columns(topics)

    if layout == "title_key_statement":
        topic_hint: str = topics[0] if isinstance(topics, list) and topics else ""
        hint_text: str = topic_hint or "משפט מפתח"
        return f'<p class="outline-key-statement">💡 {hint_text}</p>'

    if layout == "title_text":
        if isinstance(topics, list) and topics:
            topics_str: str = ", ".join(topics)
            return f'<p class="outline-desc">פסקה רציפה — הנושא: {title}. תחומים לכיסוי: {topics_str}.</p>'
        return '<p class="outline-desc">פסקת טקסט</p>'

    # Default (title_bullets and other)
    if isinstance(topics, list) and topics:
        topics_str = ", ".join(topics)
        return f'<p class="outline-desc">שדה תוכן בבולטים — הנושא: {title}. תחומים: {topics_str}.</p>'
    return '<p class="outline-desc">תוכן</p>'


def _render_outline_two_columns(topics) -> str:
    """Render a two-column layout section inside an outline card."""
    if isinstance(topics, dict):
        right: dict = topics.get("right", {})
        left: dict = topics.get("left", {})
        right_label: str = right.get("label", "ימין")
        left_label: str = left.get("label", "שמאל")
        right_topics: str = ", ".join(right.get("topics", []))
        left_topics: str = ", ".join(left.get("topics", []))
        return f'''
        <div class="outline-columns">
            <div class="outline-col"><div class="outline-col-label">▶ {right_label}</div><p class="outline-desc">{right_topics}</p></div>
            <div class="outline-col-divider"></div>
            <div class="outline-col"><div class="outline-col-label">▶ {left_label}</div><p class="outline-desc">{left_topics}</p></div>
        </div>'''
    return '<p class="outline-desc">שתי עמודות</p>'
