AVAILABLE_LAYOUTS: dict[str, str] = {
    "title_only": "כותרת בלבד",
    "title_bullets": "כותרת + בולטים",
    "title_text": "כותרת + טקסט",
    "title_two_columns": "כותרת + שתי עמודות",
    "title_key_statement": "כותרת + משפט מפתח",
    "section_header": "כותרת מפרידה",
}

LAYOUT_ICONS: dict[str, str] = {
    "title_only": "🏷️",
    "title_bullets": "📋",
    "title_text": "📝",
    "title_two_columns": "⚖️",
    "title_key_statement": "💡",
    "section_header": "📌",
}

STATUS_ICONS: dict[str, str] = {
    "validated": "✅",
    "skipped": "⏭️",
    "no_source_content": "🚫",
    "failed_validation": "❌",
    "edited_by_agent": "✏️",
    "pending_regeneration": "🔄",
}

LAYOUT_OBJECT_TEMPLATES: dict[str, list[dict]] = {
    "title_only": [],
    "section_header": [],
    "title_bullets": [
        {"object_id": "Content 1", "object_type": "text",
         "desc_template": "שדה תוכן בבולטים — הנושא: {title}. יש לחלץ את התוכן מהמקורות בלבד."}
    ],
    "title_text": [
        {"object_id": "Content 1", "object_type": "text",
         "desc_template": "שדה תוכן בפסקה רציפה — הנושא: {title}. כתוב כפסקה אחת רצופה, לא בבולטים. יש לחלץ מהמקורות בלבד."}
    ],
    "title_two_columns": [
        {"object_id": "Content Right", "object_type": "text",
         "desc_template": "שדה תוכן בבולטים — עמודה ימנית. הנושא: {title}. יש לחלץ מהמקורות בלבד."},
        {"object_id": "Content Left", "object_type": "text",
         "desc_template": "שדה תוכן בבולטים — עמודה שמאלית. הנושא: {title}. יש לחלץ מהמקורות בלבד."},
    ],
    "title_key_statement": [
        {"object_id": "Key Statement", "object_type": "text",
         "desc_template": "משפט מפתח אחד בלבד — קצר, חזק ומשמעותי. הנושא: {title}. יש לחלץ מהמקורות בלבד."}
    ],
}
