from config import STATUS_ICONS, LAYOUT_ICONS, AVAILABLE_LAYOUTS
from state import deck_state


def format_slide_preview(slide: dict) -> str:
    """Markdown preview for slide-level tab."""
    lines = []
    lines.append(f"**שקף {slide.get('slide_num')}:** {slide.get('slide_description', '')}")
    lines.append(f"**סטטוס:** {slide.get('generation_status', 'ממתין')}")
    lines.append("")
    for obj in slide.get("slide_objects", []):
        obj_id = obj.get("object_id", "?")
        obj_name = obj.get("object_name", "?")
        status = obj.get("validation_status", "לא נוצר")
        content = obj.get("generated_content", "")
        icon = STATUS_ICONS.get(status, "⏳")
        lines.append("---")
        lines.append(f"{icon} **{obj_id}** — {obj_name}")
        lines.append(f"סטטוס: {status}")
        lines.append(f"תוכן:")
        lines.append(f"```\n{content or '(ריק)'}\n```")
    return "\n".join(lines)


def render_slide_html(slide: dict, slide_index: int, total_slides: int) -> str:
    """Render a single slide as HTML card."""
    slide_num = slide.get("slide_num", "?")
    layout = slide.get("slide_layout", "title_bullets")
    title_text = ""
    body_parts = []

    for obj in slide.get("slide_objects", []):
        obj_name = obj.get("object_name", "").lower()
        obj_id = obj.get("object_id", "")
        content = obj.get("generated_content", "")
        status = obj.get("validation_status", "")
        if not content:
            continue
        if "כותרת" in obj_name or "תת" in obj_name:
            title_text = content
        else:
            icon = STATUS_ICONS.get(status, "⏳")

            if obj_id == "Key Statement":
                body_parts.append(f'<div class="slide-key-statement">{content}</div>')
            elif obj_id in ("Content Right", "Content Left"):
                col_class = "slide-col-right" if obj_id == "Content Right" else "slide-col-left"
                col_label = obj.get("object_name", "")
                body_parts.append(_render_content_block(content, icon, col_label, col_class))
            else:
                body_parts.append(_render_content_block(content, icon, obj.get("object_name", "")))

    if not title_text:
        title_text = slide.get("slide_description", "")

    if layout == "title_two_columns" and any("slide-col-" in p for p in body_parts):
        body_html = f'<div class="slide-two-columns">{"".join(body_parts)}</div>'
    elif body_parts:
        body_html = "\n".join(body_parts)
    elif layout in ("title_only", "section_header"):
        body_html = ''
    else:
        body_html = '<p class="slide-empty">אין תוכן</p>'

    if layout == "section_header":
        return f'''
        <div class="slide-card slide-section-header">
            <div class="slide-section-title">{title_text}</div>
            <div class="slide-footer">שקף {slide_num} מתוך {total_slides}</div>
        </div>'''

    return f'''
    <div class="slide-card">
        <div class="slide-title-bar">{title_text}</div>
        <div class="slide-body">{body_html}</div>
        <div class="slide-footer">שקף {slide_num} מתוך {total_slides}</div>
    </div>'''


def _render_content_block(content, icon, label, wrapper_class=None):
    """Render a content block as bullets or paragraph."""
    is_bullets = "\n" in content and any(
        line.strip().startswith(("-", "•", "–")) for line in content.split("\n")
    )
    if is_bullets:
        items = ""
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith(("-", "•", "–")):
                line = line.lstrip("-•– ").strip()
            if line:
                items += f"<li>{line}</li>"
        inner = f'<div class="slide-obj-label">{icon} {label}</div><ul class="slide-bullets">{items}</ul>'
    else:
        inner = f'<div class="slide-obj-label">{icon} {label}</div><p class="slide-text">{content}</p>'

    if wrapper_class:
        label_class = "slide-col-label" if "col" in wrapper_class else "slide-obj-label"
        if is_bullets:
            inner = f'<div class="{label_class}">{icon} {label}</div><ul class="slide-bullets">{items}</ul>'
        else:
            inner = f'<div class="{label_class}">{icon} {label}</div><p class="slide-text">{content}</p>'
        return f'<div class="{wrapper_class}">{inner}</div>'
    return inner


def render_deck_preview(skeleton: dict = None) -> str:
    """Render the full deck as scrollable HTML preview."""
    if skeleton is None:
        skeleton = deck_state.get("skeleton")
    if skeleton is None:
        return '<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>'
    slides = skeleton.get("slides", [])
    total = len(slides)
    slides_html = "\n".join(render_slide_html(slide, i, total) for i, slide in enumerate(slides))
    return f'''
    <div class="deck-preview">
        <div class="preview-header">📊 תצוגה מקדימה — {total} שקפים</div>
        <div class="slides-container">{slides_html}</div>
    </div>'''


def render_outline_html(outline: dict) -> str:
    """Render proposed outline as HTML preview for approval."""
    slides = outline.get("slides", [])
    total = len(slides)

    with_content = sum(1 for s in slides if s.get("has_content", True))
    without_content = total - with_content

    warning_html = ""
    if without_content > 0:
        warning_html = f'<div class="outline-warning">⚠️ {without_content} שקפים מסומנים כחסרי מידע מספיק — מומלץ להוסיף מידע או להסיר אותם</div>'

    slides_html = ""
    for slide in slides:
        slide_num = slide.get("slide_num", "?")
        title = slide.get("title", "ללא כותרת")
        layout = slide.get("layout", "title_bullets")
        topics = slide.get("topics", [])
        has_content = slide.get("has_content", True)

        content_icon = "✅" if has_content else "⚠️"
        card_class = "outline-card" if has_content else "outline-card outline-card-warning"
        layout_icon = LAYOUT_ICONS.get(layout, "📋")
        layout_label = AVAILABLE_LAYOUTS.get(layout, layout)

        if layout in ("title_only", "section_header"):
            content_html = '<p class="outline-placeholder">שקף כותרת בלבד</p>'
        elif layout == "title_two_columns":
            if isinstance(topics, dict):
                right = topics.get("right", {})
                left = topics.get("left", {})
                right_label = right.get("label", "ימין")
                left_label = left.get("label", "שמאל")
                right_topics = ", ".join(right.get("topics", []))
                left_topics = ", ".join(left.get("topics", []))
                content_html = f'''
                <div class="outline-columns">
                    <div class="outline-col">
                        <div class="outline-col-label">▶ {right_label}</div>
                        <p class="outline-desc">{right_topics}</p>
                    </div>
                    <div class="outline-col-divider"></div>
                    <div class="outline-col">
                        <div class="outline-col-label">▶ {left_label}</div>
                        <p class="outline-desc">{left_topics}</p>
                    </div>
                </div>'''
            else:
                content_html = '<p class="outline-desc">שתי עמודות</p>'
        elif layout == "title_key_statement":
            topic_hint = topics[0] if isinstance(topics, list) and topics else ""
            content_html = f'<p class="outline-key-statement">💡 {topic_hint}</p>' if topic_hint else '<p class="outline-key-statement">💡 משפט מפתח</p>'
        elif layout == "title_text":
            if isinstance(topics, list) and topics:
                topics_str = ", ".join(topics)
                content_html = f'<p class="outline-desc">פסקה רציפה — הנושא: {title}. תחומים לכיסוי: {topics_str}.</p>'
            else:
                content_html = '<p class="outline-desc">פסקת טקסט</p>'
        else:
            if isinstance(topics, list) and topics:
                topics_str = ", ".join(topics)
                content_html = f'<p class="outline-desc">שדה תוכן בבולטים — הנושא: {title}. תחומים לכיסוי: {topics_str}.</p>'
            elif not has_content:
                content_html = '<p class="outline-placeholder outline-placeholder-warning">נדרש מידע נוסף</p>'
            else:
                content_html = '<p class="outline-desc">תוכן בבולטים</p>'

        slides_html += f'''
        <div class="{card_class}">
            <div class="outline-num">{content_icon} שקף {slide_num}</div>
            <div class="outline-title">{title}</div>
            <div class="outline-layout-badge">{layout_icon} {layout_label}</div>
            {content_html}
        </div>'''

    return f'''
    <div class="deck-preview">
        {warning_html}
        <div class="outline-container">{slides_html}</div>
    </div>'''