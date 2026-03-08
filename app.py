import re
import os
import json
import copy
import gradio as gr
from datetime import datetime
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from slide_agent import SlideAgent

load_dotenv()
MAX_REVISIONS = 30


class RevisionManager:
    def __init__(self):
        self.revisions = []
        self.current_revision_id = 0

    def save_revision(self, skeleton: dict, action: str, description: str) -> int:
        self.current_revision_id += 1
        revision = {
            "revision_id": self.current_revision_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "description": description,
            "snapshot": copy.deepcopy(skeleton)
        }
        self.revisions.append(revision)
        if len(self.revisions) > MAX_REVISIONS:
            self.revisions = [self.revisions[0]] + self.revisions[-(MAX_REVISIONS - 1):]
        return self.current_revision_id

    def get_revision(self, revision_id: int) -> dict | None:
        for rev in self.revisions:
            if rev["revision_id"] == revision_id:
                return rev
        return None

    def restore_revision(self, revision_id: int) -> dict | None:
        rev = self.get_revision(revision_id)
        if rev is None:
            return None
        return copy.deepcopy(rev["snapshot"])

    def get_revision_choices(self) -> list[str]:
        choices = []
        for rev in reversed(self.revisions):
            rid = rev["revision_id"]
            ts = rev["timestamp"]
            action = rev["action"]
            desc = rev["description"]
            choices.append(f"[גרסה {rid}] {ts} — {action}: {desc}")
        return choices

    def get_latest_id(self) -> int:
        return self.current_revision_id

    def reset(self):
        self.revisions = []
        self.current_revision_id = 0


# ──────────────────────────────────────────────
#  State Management
# ──────────────────────────────────────────────

deck_state = {
    "skeleton": None,
    "agent": None,
    "revision_manager": RevisionManager(),
    "pending_outline": None  # holds proposed structure before approval
}


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def get_slide_choices():
    if deck_state["skeleton"] is None:
        return []
    choices = []
    for slide in deck_state["skeleton"].get("slides", []):
        num = slide.get("slide_num", "?")
        desc = slide.get("slide_description", "ללא תיאור")
        choices.append(f"[שקף {num}] {desc}")
    return choices


def parse_slide_num_from_selection(selection: str) -> str | None:
    match = re.match(r"\[שקף (.+?)\]", selection)
    return match.group(1) if match else None


def get_slide_by_num(slide_num: str) -> dict | None:
    if deck_state["skeleton"] is None:
        return None
    for slide in deck_state["skeleton"]["slides"]:
        if str(slide.get("slide_num", "")) == slide_num:
            return slide
    return None


def format_slide_preview(slide: dict) -> str:
    lines = []
    lines.append(f"**שקף {slide.get('slide_num')}:** {slide.get('slide_description', '')}")
    lines.append(f"**סטטוס:** {slide.get('generation_status', 'ממתין')}")
    lines.append("")
    for obj in slide.get("slide_objects", []):
        obj_id = obj.get("object_id", "?")
        obj_name = obj.get("object_name", "?")
        status = obj.get("validation_status", "לא נוצר")
        content = obj.get("generated_content", "")
        icon = {"validated": "✅", "skipped": "⏭️", "manual_fix": "✏️",
                "edited_by_agent": "🤖", "failed_validation": "❌"}.get(status, "⏳")
        lines.append(f"---")
        lines.append(f"{icon} **{obj_id}** — {obj_name}")
        lines.append(f"סטטוס: {status}")
        lines.append(f"תוכן:")
        lines.append(f"```\n{content or '(ריק)'}\n```")
    return "\n".join(lines)


def render_slide_html(slide: dict, slide_index: int, total_slides: int) -> str:
    slide_num = slide.get("slide_num", "?")
    title_text = ""
    body_parts = []

    for obj in slide.get("slide_objects", []):
        obj_name = obj.get("object_name", "").lower()
        content = obj.get("generated_content", "")
        status = obj.get("validation_status", "")
        if not content:
            continue
        if "כותרת" in obj_name or "תת" in obj_name:
            title_text = content
        else:
            icon = {"validated": "✅", "skipped": "⏭️", "manual_fix": "✏️",
                    "edited_by_agent": "🤖", "failed_validation": "❌"}.get(status, "⏳")
            if "\n" in content and any(line.strip().startswith(("-", "•", "–")) for line in content.split("\n")):
                items = ""
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith(("-", "•", "–")):
                        line = line.lstrip("-•– ").strip()
                    if line:
                        items += f"<li>{line}</li>"
                body_parts.append(f'<div class="slide-obj-label">{icon} {obj.get("object_name", "")}</div><ul class="slide-bullets">{items}</ul>')
            else:
                body_parts.append(f'<div class="slide-obj-label">{icon} {obj.get("object_name", "")}</div><p class="slide-text">{content}</p>')

    if not title_text:
        title_text = slide.get("slide_description", "")
    body_html = "\n".join(body_parts) if body_parts else '<p class="slide-empty">אין תוכן</p>'

    return f'''
    <div class="slide-card">
        <div class="slide-title-bar">{title_text}</div>
        <div class="slide-body">{body_html}</div>
        <div class="slide-footer">שקף {slide_num} מתוך {total_slides}</div>
    </div>
    '''


def render_deck_preview(skeleton: dict = None) -> str:
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
    </div>
    '''


def render_outline_html(outline: dict) -> str:
    """Render proposed outline as HTML preview for approval."""
    slides = outline.get("slides", [])
    total = len(slides)
    assessment = outline.get("content_assessment", "")

    with_content = sum(1 for s in slides if s.get("has_content", True))
    without_content = total - with_content

    assessment_html = ""
    if assessment:
        assessment_html = f'<div class="outline-assessment">💡 {assessment}</div>'

    warning_html = ""
    if without_content > 0:
        warning_html = f'<div class="outline-warning">⚠️ {without_content} שקפים מסומנים כחסרי מידע מספיק — מומלץ להוסיף מידע או להסיר אותם</div>'

    slides_html = ""
    for slide in slides:
        slide_num = slide.get("slide_num", "?")
        title = slide.get("title", "ללא כותרת")
        topics = slide.get("topics", slide.get("bullets", []))
        has_content = slide.get("has_content", True)

        content_icon = "✅" if has_content else "⚠️"
        card_class = "outline-card" if has_content else "outline-card outline-card-warning"

        # Build content description from topics
        if not topics:
            # Title-only slide (e.g., first slide)
            content_html = '<p class="outline-placeholder">שקף כותרת בלבד</p>'
        elif has_content:
            topics_str = ", ".join(topics)
            desc = f"שדה תוכן בבולטים — הנושא: {title}. תחומים לכיסוי: {topics_str}."
            content_html = f'<p class="outline-desc">{desc}</p>'
        else:
            content_html = '<p class="outline-placeholder outline-placeholder-warning">נדרש מידע נוסף</p>'

        slides_html += f'''
        <div class="{card_class}">
            <div class="outline-num">{content_icon} שקף {slide_num}</div>
            <div class="outline-title">{title}</div>
            {content_html}
        </div>
        '''

    return f'''
    <div class="deck-preview">
        {warning_html}
        <div class="outline-container">{slides_html}</div>
    </div>
    '''


def apply_edits_to_skeleton(edit_data: dict, scope_slide_num: str = None) -> int:
    skeleton = deck_state["skeleton"]
    applied_count = 0
    for edit in edit_data.get("edits", []):
        edit_slide_num = str(edit.get("slide_num", ""))
        edit_object_id = edit.get("object_id", "")
        edit_object_name = edit.get("object_name", "")
        new_content = edit.get("new_content", "")
        matched = False
        if scope_slide_num:
            edit_slide_num = scope_slide_num
        for slide in skeleton["slides"]:
            if str(slide.get("slide_num", "")) == edit_slide_num:
                for obj in slide.get("slide_objects", []):
                    obj_id = obj.get("object_id", "")
                    obj_name = obj.get("object_name", "")
                    if (edit_object_id and obj_id == edit_object_id) or \
                       (edit_object_name and obj_name == edit_object_name):
                        obj["generated_content"] = new_content
                        obj["validation_status"] = "edited_by_agent"
                        applied_count += 1
                        matched = True
                        break
                if matched:
                    break
        if not matched and edit_object_name:
            for slide in skeleton["slides"]:
                for obj in slide.get("slide_objects", []):
                    if obj.get("object_name", "") == edit_object_name:
                        obj["generated_content"] = new_content
                        obj["validation_status"] = "edited_by_agent"
                        applied_count += 1
                        matched = True
                        break
                if matched:
                    break
    return applied_count


def call_edit_llm(prompt: str) -> str:
    agent = deck_state["agent"]
    response = InferenceClient(
        provider="groq",
        api_key=os.getenv("HF_TOKEN")
    ).chat.completions.create(
        model=agent.model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1000
    )
    return response.choices[0].message.content


def call_llm_raw(prompt: str, model_name: str = "openai/gpt-oss-120b") -> str:
    """Call LLM without needing an agent instance."""
    response = InferenceClient(
        provider="groq",
        api_key=os.getenv("HF_TOKEN")
    ).chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000
    )
    return response.choices[0].message.content


def parse_llm_json(raw_response: str) -> dict:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
    if cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[:-1])
    return json.loads(cleaned)


def detect_slide_count(user_prompt: str) -> int | None:
    """Try to detect if the user specified a slide count in their prompt."""
    patterns = [
        r'(\d+)\s*שקפים',
        r'(\d+)\s*שקף',
        r'(\d+)\s*slides?',
        r'מצגת\s*(?:של|בת|עם)\s*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, user_prompt)
        if match:
            return int(match.group(1))
    return None


# ──────────────────────────────────────────────
#  Structure Agent (template-free generation)
# ──────────────────────────────────────────────

def generate_outline(user_prompt: str, document_text: str, slide_count: int | None) -> dict:
    """Generate a proposed presentation structure from prompt + document."""

    if slide_count:
        count_instruction = f"מספר שקפים מבוקש: {slide_count}"
        count_rule = f"4. עדיף להציע פחות שקפים עם נושאים אמיתיים מאשר {slide_count} שקפים עם נושאים בדויים.\n5. אם המידע מספיק רק ל-3 שקפים למרות שנדרשו {slide_count} — הצע 3 בלבד וציין זאת."
    else:
        count_instruction = "מספר שקפים: לא צוין — הצע מספר שקפים מתאים על בסיס כמות המידע הזמין."
        count_rule = "4. התאם את מספר השקפים לכמות המידע הזמין. אל תציע שקפים שאין להם מספיק מידע."

    prompt = f"""אתה מתכנן מבנה מצגות מקצועי. תפקידך להציע מבנה (structure) בלבד — לא תוכן סופי.

═══ מקורות מידע ═══

הנחיית המשתמש:
{user_prompt}

מסמך מקור:
{document_text or "לא סופק"}

═══════════════════

{count_instruction}

עליך ליצור מבנה מצגת. עבור כל שקף, הצע:
- כותרת (title) — כותרת קצרה וברורה לשקף
- נושאים (topics) — 2-4 נושאים שהשקף יכסה. אלה תיאורי נושאים בלבד, לא תוכן סופי.
  - דוגמה נכונה: "תיאור כרונולוגי של האירוע"
  - דוגמה שגויה: "בתאריך 12 במרץ 2025 התרחש אירוע בטיחות בבסיס הקריה"
- has_content (true/false) — האם יש מספיק מידע במקורות לכסות את הנושאים האלה

כללים קריטיים:
1. הנושאים (topics) מתארים מה השקף יכסה — לא מה הוא יגיד. הם כותרות נושא, לא משפטי תוכן.
2. אין לכלול עובדות, תאריכים, שמות, או פרטים ספציפיים בנושאים — אלה יופקו בשלב הבא על ידי סוכן אחר.
3. אם אין מספיק מידע במקורות לכסות שקף — סמן has_content: false והנושא יהיה "נדרש מידע נוסף".
{count_rule}
6. השקף הראשון תמיד יהיה שקף כותרת/פתיחה, ללא תוכן כלל, רק כותרת. topics יהיה רשימה ריקה [].
7. השקף האחרון יהיה סיכום/המלצות (אם יש מספיק מידע).
8. סדר השקפים צריך להיות הגיוני.
9. הכל בעברית.

החזר תשובה בפורמט JSON בלבד, ללא טקסט נוסף:

{{
  "preset_name": "מבנה מותאם",
  "content_assessment": "הערכה קצרה של כמות המידע הזמין ומספר השקפים שניתן לכסות",
  "slides": [
    {{
      "slide_num": 1,
      "title": "כותרת המצגת",
      "topics": [],
      "has_content": true
    }},
    {{
      "slide_num": 2,
      "title": "כותרת השקף",
      "topics": [
        "נושא ראשון שהשקף יכסה",
        "נושא שני שהשקף יכסה"
      ],
      "has_content": true
    }}
  ]
}}
"""

    raw_response = call_llm_raw(prompt)
    return parse_llm_json(raw_response)


def outline_to_skeleton(outline: dict) -> dict:
    """Convert an approved outline into a full skeleton JSON compatible with SlideAgent."""
    skeleton = {
        "preset_name": outline.get("preset_name", "מבנה מותאם"),
        "slides": []
    }

    for slide in outline.get("slides", []):
        slide_num = slide.get("slide_num", 1)
        title = slide.get("title", "")
        topics = slide.get("topics", slide.get("bullets", []))
        has_content = slide.get("has_content", True)

        slide_entry = {
            "slide_num": slide_num,
            "slide_description": title,
            "slide_objects": [
                {
                    "object_id": "Title 1",
                    "object_name": f"כותרת {title}",
                    "object_type": "text",
                    "object_description": f'כותרת בשם "{title}"',
                }
            ]
        }

        # Only add Content object if there are topics (not a title-only slide)
        if topics:
            topics_str = ", ".join(topics)
            object_desc = (
                f"שדה תוכן בבולטים — הנושא: {title}. "
                f"תחומים לכיסוי: {topics_str}. "
                f"יש לחלץ את התוכן מהנחיית המשתמש והמסמך בלבד — אין להמציא פרטים."
            )
            slide_entry["slide_objects"].append({
                "object_id": "Content 1",
                "object_name": f"תוכן שקף {slide_num}",
                "object_type": "text",
                "object_description": object_desc,
                "has_source_content": has_content
            })

        skeleton["slides"].append(slide_entry)

    return skeleton


# ──────────────────────────────────────────────
#  Generation (with template / without template)
# ──────────────────────────────────────────────

def handle_generate(file, user_prompt, document_text, slide_count_input):
    """
    Main generation handler:
    - With template → generate directly
    - Without template → generate outline for approval
    """

    has_template = file is not None
    has_prompt = bool(user_prompt and user_prompt.strip())

    # Validation: no template → prompt is mandatory
    if not has_template and not has_prompt:
        return (
            "❌ יש להזין הנחיית משתמש כאשר לא נבחרה תבנית",
            '<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>',
            "{}",
            gr.update(visible=False),
            "",
        )

    # ── Path A: Template provided → generate directly ──
    if has_template:
        content = file.read().decode("utf-8") if hasattr(file, "read") else open(file, "r", encoding="utf-8").read()
        skeleton = json.loads(content)

        agent = SlideAgent(language="hebrew")
        rev_manager = RevisionManager()

        deck_state["skeleton"] = skeleton
        deck_state["agent"] = agent
        deck_state["user_prompt"] = user_prompt
        deck_state["document_text"] = document_text or ""
        deck_state["revision_manager"] = rev_manager
        deck_state["pending_outline"] = None

        for slide in skeleton["slides"]:
            agent.generate_slide(
                slide=slide,
                user_prompt=user_prompt,
                document_text=document_text or ""
            )

        rev_manager.save_revision(
            skeleton=skeleton,
            action="יצירה",
            description="יצירת מצגת ראשונית עם תבנית"
        )

        full_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
        preview_html = render_deck_preview(skeleton)

        return (
            "✅ המצגת נוצרה בהצלחה",
            preview_html,
            full_json,
            gr.update(visible=False),
            "",
        )

    # ── Path B: No template → determine slide count then generate outline ──

    # Priority: 1) detected from prompt text, 2) dropdown selection, 3) let Structure Agent decide
    detected_count = detect_slide_count(user_prompt)

    if detected_count:
        slide_count = detected_count
    elif slide_count_input and slide_count_input != "אוטומטי" and str(slide_count_input).isdigit():
        slide_count = int(slide_count_input)
    else:
        slide_count = None  # let Structure Agent decide

    # Store prompt data
    deck_state["user_prompt"] = user_prompt
    deck_state["document_text"] = document_text or ""

    # Content threshold warning
    total_input_words = len(user_prompt.split()) + len((document_text or "").split())
    content_warning = ""
    if total_input_words < 20:
        content_warning = (
            "⚠️ שים לב: כמות המידע שסופקה מצומצמת "
            f"({total_input_words} מילים). "
            "ייתכן שחלק מהשקפים לא יכילו מספיק תוכן. "
            "מומלץ להוסיף מסמך מקור או להרחיב את ההנחיה לתוצאות טובות יותר.\n\n"
        )

    # Generate outline
    try:
        outline = generate_outline(user_prompt, document_text, slide_count)
        deck_state["pending_outline"] = outline

        outline_html = render_outline_html(outline)

        return (
            f"{content_warning}📋 מבנה מוצע עם {len(outline.get('slides', []))} שקפים — בדוק ואשר או ערוך",
            '<div class="preview-empty">אשר את המבנה המוצע כדי ליצור את המצגת</div>',
            "{}",
            gr.update(visible=True),
            outline_html,
        )
    except Exception as e:
        return (
            f"❌ שגיאה ביצירת מבנה: {str(e)}",
            '<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>',
            "{}",
            gr.update(visible=False),
            "",
        )


def approve_outline():
    """Approve the proposed outline and run full generation."""
    outline = deck_state.get("pending_outline")
    if outline is None:
        return (
            "❌ אין מבנה מוצע לאישור",
            '<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>',
            "{}",
            gr.update(visible=False),
            "",
        )

    # Convert outline to skeleton
    skeleton = outline_to_skeleton(outline)

    agent = SlideAgent(language="hebrew")
    rev_manager = RevisionManager()

    deck_state["skeleton"] = skeleton
    deck_state["agent"] = agent
    deck_state["revision_manager"] = rev_manager
    deck_state["pending_outline"] = None

    user_prompt = deck_state.get("user_prompt", "")
    document_text = deck_state.get("document_text", "")

    for slide in skeleton["slides"]:
        agent.generate_slide(
            slide=slide,
            user_prompt=user_prompt,
            document_text=document_text
        )

    rev_manager.save_revision(
        skeleton=skeleton,
        action="יצירה",
        description="יצירת מצגת ממבנה מותאם"
    )

    full_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
    preview_html = render_deck_preview(skeleton)

    return (
        "✅ המצגת נוצרה בהצלחה ממבנה מותאם",
        preview_html,
        full_json,
        gr.update(visible=False),  # hide outline section
        "",
    )


def edit_outline(edit_instruction):
    """Edit the proposed outline based on user instruction before approval."""
    outline = deck_state.get("pending_outline")
    if outline is None:
        return "❌ אין מבנה מוצע לעריכה", ""

    outline_json = json.dumps(outline, indent=2, ensure_ascii=False)

    prompt = f"""אתה עורך מבנה מצגות. המשתמש מבקש לשנות את המבנה המוצע.

המבנה הנוכחי (JSON):
{outline_json}

בקשת השינוי:
{edit_instruction}

כללים:
1. בצע את השינוי המבוקש בלבד.
2. שמור על הפורמט המקורי — כל שקף כולל title, topics (נושאים), ו-has_content.
3. ה-topics הם תיאורי נושאים בלבד, לא תוכן סופי.
4. עדכן את slide_num בהתאם אם הוספת או הסרת שקפים.
5. הכל בעברית.

החזר את המבנה המעודכן בפורמט JSON בלבד, ללא טקסט נוסף:

{{
  "preset_name": "מבנה מותאם",
  "content_assessment": "הערכה מעודכנת",
  "slides": [
    {{
      "slide_num": 1,
      "title": "כותרת השקף",
      "topics": ["נושא ראשון", "נושא שני"],
      "has_content": true
    }}
  ]
}}
"""

    try:
        raw_response = call_llm_raw(prompt)
        updated_outline = parse_llm_json(raw_response)
        deck_state["pending_outline"] = updated_outline

        outline_html = render_outline_html(updated_outline)
        return f"✅ המבנה עודכן — {len(updated_outline.get('slides', []))} שקפים", outline_html
    except Exception as e:
        return f"❌ שגיאה בעדכון מבנה: {str(e)}", render_outline_html(outline)


# ──────────────────────────────────────────────
#  Deck-Level Chat Edit
# ──────────────────────────────────────────────

def deck_chat_edit(user_message, chat_history):
    if deck_state["skeleton"] is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש ליצור מצגת קודם בלשונית 'יצירת מצגת'."})
        return chat_history, '<div class="preview-empty">התצוגה תתעדכן לאחר עריכה</div>', json.dumps({}, indent=2, ensure_ascii=False), gr.update(choices=[])

    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_message})

    deck_json = json.dumps(skeleton, indent=2, ensure_ascii=False)

    edit_prompt = f"""אתה עורך מצגות מקצועי. המשתמש מבקש לערוך תוכן במצגת.

המצגת הנוכחית (JSON):
{deck_json}

═══ מקורות מידע (מקור האמת) ═══

ההנחיה המקורית של המשתמש:
{deck_state.get("user_prompt", "")}

מסמך מקור:
{deck_state.get("document_text", "לא סופק")}

בקשת העריכה:
{user_message}

═══════════════════════════════════

חשוב — מבנה המצגת:
- כל שקף מזוהה לפי "slide_num" (מספר שלם: 1, 2, 3...).
- כל אובייקט בשקף מזוהה לפי:
  - "object_id" — מזהה טכני כמו "Rectangle 2", "Title 1". שים לב: object_id יכול לחזור על עצמו בין שקפים שונים!
  - "object_name" — שם תיאורי ייחודי כמו "תוכן רקע האירוע".

כללי עריכה קריטיים:
1. בצע אך ורק את השינוי שהמשתמש ביקש — לא יותר ולא פחות.
2. אם המשתמש מבקש להוסיף מידע ספציפי — הוסף בדיוק את מה שנאמר. אל תמציא פרטים נוספים.
3. אם המשתמש מבקש לשנות סגנון — שנה את הסגנון בלבד, שמור על העובדות הקיימות.
4. אל תמציא עובדות, תאריכים, שמות, או מידע שלא מופיע בהנחיית המשתמש, במסמך המקור, או בבקשת העריכה.
5. אל תרחיב את התוכן מעבר למה שנדרש.
6. כל התוכן חייב להיות בעברית תקינה.
7. חובה לשמור על הפורמט שמוגדר ב-object_description של כל אובייקט. לדוגמה: אם כתוב "בבולטים" — התוכן חייב להיות בבולטים (כל נקודה בשורה חדשה עם מקף). אם כתוב "פסקה" — כתוב כפסקה רציפה. הפורמט מ-object_description גובר תמיד.

עליך:
1. לזהות את האובייקט/ים שהמשתמש מתייחס אליהם.
2. לקרוא את ה-object_description של האובייקט כדי להבין את הפורמט הנדרש.
3. לבצע את השינוי המבוקש על התוכן הקיים (generated_content) תוך שמירה על הפורמט.
3. להחזיר תשובה בפורמט JSON בלבד, ללא טקסט נוסף:

{{
  "edits": [
    {{
      "slide_num": 2,
      "object_id": "Rectangle 2",
      "object_name": "תוכן רקע האירוע",
      "new_content": "התוכן החדש או המעודכן"
    }}
  ],
  "summary": "תיאור קצר של מה שנעשה"
}}

אם לא הצלחת לזהות את האובייקט — החזר:
{{
  "edits": [],
  "summary": "לא הצלחתי לזהות את האובייקט. אנא ציין מספר שקף (slide_num) ושם אובייקט (object_name)."
}}
"""

    try:
        raw_response = call_edit_llm(edit_prompt)
        edit_data = parse_llm_json(raw_response)
        applied_count = apply_edits_to_skeleton(edit_data)

        summary = edit_data.get("summary", "")
        if applied_count > 0:
            rev_manager.save_revision(skeleton=skeleton, action="עריכה", description=summary)
            rev_id = rev_manager.get_latest_id()
            assistant_msg = f"✅ {summary} ({applied_count} אובייקטים עודכנו) — גרסה {rev_id}"
        else:
            raw_edits = json.dumps(edit_data.get("edits", []), ensure_ascii=False, indent=2)
            existing_ids = []
            for s in skeleton["slides"]:
                for o in s.get("slide_objects", []):
                    existing_ids.append(f"slide_num {s.get('slide_num')}: {o.get('object_id')} ({o.get('object_name')})")
            assistant_msg = (
                f"⚠️ {summary}\n\n"
                f"הסוכן החזיר:\n{raw_edits}\n\n"
                f"אובייקטים קיימים במצגת:\n" + "\n".join(existing_ids)
            )

    except (json.JSONDecodeError, KeyError) as e:
        assistant_msg = f"⚠️ לא הצלחתי לעבד את התשובה. נסה לנסח מחדש את הבקשה.\n\nשגיאה: {str(e)}"

    chat_history.append({"role": "assistant", "content": assistant_msg})
    full_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
    preview_html = render_deck_preview(skeleton)
    revision_choices = rev_manager.get_revision_choices()

    return chat_history, preview_html, full_json, gr.update(choices=revision_choices)


# ──────────────────────────────────────────────
#  Slide-Level Chat Edit
# ──────────────────────────────────────────────

def on_slide_selected(slide_selection):
    if not slide_selection or deck_state["skeleton"] is None:
        return "בחר שקף כדי לראות את התוכן שלו"
    slide_num = parse_slide_num_from_selection(slide_selection)
    slide = get_slide_by_num(slide_num)
    if slide is None:
        return "❌ שקף לא נמצא"
    return format_slide_preview(slide)


def slide_chat_edit(user_message, slide_selection, chat_history):
    if deck_state["skeleton"] is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש ליצור מצגת קודם בלשונית 'יצירת מצגת'."})
        return chat_history, "בחר שקף כדי לראות את התוכן שלו", gr.update(choices=[])

    if not slide_selection:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש לבחור שקף קודם."})
        return chat_history, "", gr.update(choices=[])

    slide_num = parse_slide_num_from_selection(slide_selection)
    slide = get_slide_by_num(slide_num)

    if slide is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ שקף לא נמצא."})
        return chat_history, "", gr.update(choices=[])

    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_message})

    slide_json = json.dumps(slide, indent=2, ensure_ascii=False)
    obj_list_str = ', '.join(o.get('object_id', '') + ' (' + o.get('object_name', '') + ')' for o in slide.get('slide_objects', []))

    edit_prompt = f"""אתה עורך מצגות מקצועי. המשתמש מבקש לערוך תוכן בשקף ספציפי.

השקף הנוכחי (JSON):
{slide_json}

═══ מקורות מידע (מקור האמת) ═══

ההנחיה המקורית של המשתמש:
{deck_state.get("user_prompt", "")}

מסמך מקור:
{deck_state.get("document_text", "לא סופק")}

בקשת העריכה:
{user_message}

═══════════════════════════════════

חשוב — מבנה השקף:
- השקף הוא שקף מספר {slide_num}.
- כל אובייקט בשקף מזוהה לפי:
  - "object_id" — מזהה טכני כמו "Rectangle 2", "Title 1".
  - "object_name" — שם תיאורי כמו "תוכן רקע האירוע".

כללי עריכה קריטיים:
1. בצע אך ורק את השינוי שהמשתמש ביקש — לא יותר ולא פחות.
2. אם המשתמש מבקש להוסיף מידע ספציפי — הוסף בדיוק את מה שנאמר. אל תמציא פרטים נוספים.
3. אם המשתמש מבקש לשנות סגנון — שנה את הסגנון בלבד, שמור על העובדות הקיימות.
4. אל תמציא עובדות, תאריכים, שמות, או מידע שלא מופיע בהנחיית המשתמש, במסמך המקור, או בבקשת העריכה.
5. אל תרחיב את התוכן מעבר למה שנדרש.
6. כל התוכן חייב להיות בעברית תקינה.
7. חובה לשמור על הפורמט שמוגדר ב-object_description של כל אובייקט. לדוגמה: אם כתוב "בבולטים" — התוכן חייב להיות בבולטים (כל נקודה בשורה חדשה עם מקף). אם כתוב "פסקה" — כתוב כפסקה רציפה. הפורמט מ-object_description גובר תמיד.

עליך:
1. לזהות את האובייקט/ים שהמשתמש מתייחס אליהם בתוך השקף הזה בלבד.
2. לקרוא את ה-object_description של האובייקט כדי להבין את הפורמט הנדרש.
3. לבצע את השינוי המבוקש על התוכן הקיים (generated_content) תוך שמירה על הפורמט.
3. להחזיר תשובה בפורמט JSON בלבד, ללא טקסט נוסף:

{{
  "edits": [
    {{
      "slide_num": {slide_num},
      "object_id": "Rectangle 2",
      "object_name": "תוכן רקע האירוע",
      "new_content": "התוכן החדש או המעודכן"
    }}
  ],
  "summary": "תיאור קצר של מה שנעשה"
}}

אם לא הצלחת לזהות את האובייקט — החזר:
{{
  "edits": [],
  "summary": "לא הצלחתי לזהות את האובייקט. האובייקטים הקיימים בשקף הם: {obj_list_str}"
}}
"""

    try:
        raw_response = call_edit_llm(edit_prompt)
        edit_data = parse_llm_json(raw_response)
        applied_count = apply_edits_to_skeleton(edit_data, scope_slide_num=slide_num)

        summary = edit_data.get("summary", "")
        if applied_count > 0:
            rev_manager.save_revision(
                skeleton=skeleton,
                action=f"עריכת שקף {slide_num}",
                description=summary
            )
            rev_id = rev_manager.get_latest_id()
            assistant_msg = f"✅ {summary} ({applied_count} אובייקטים עודכנו) — גרסה {rev_id}"
        else:
            obj_list = [f"{o.get('object_id')} ({o.get('object_name')})" for o in slide.get("slide_objects", [])]
            assistant_msg = (
                f"⚠️ {summary}\n\n"
                f"אובייקטים בשקף {slide_num}:\n" + "\n".join(obj_list)
            )

    except (json.JSONDecodeError, KeyError) as e:
        assistant_msg = f"⚠️ לא הצלחתי לעבד את התשובה. נסה לנסח מחדש את הבקשה.\n\nשגיאה: {str(e)}"

    chat_history.append({"role": "assistant", "content": assistant_msg})

    updated_slide = get_slide_by_num(slide_num)
    preview = format_slide_preview(updated_slide) if updated_slide else ""
    revision_choices = rev_manager.get_revision_choices()

    return chat_history, preview, gr.update(choices=revision_choices)


# ──────────────────────────────────────────────
#  Revision Management
# ──────────────────────────────────────────────

def restore_revision(revision_selection):
    if not revision_selection or deck_state["skeleton"] is None:
        return "❌ יש לבחור גרסה", json.dumps(deck_state.get("skeleton", {}), indent=2, ensure_ascii=False)
    rev_manager = deck_state["revision_manager"]
    match = re.match(r"\[גרסה (\d+)\]", revision_selection)
    if not match:
        return "❌ לא ניתן לזהות מספר גרסה", json.dumps(deck_state["skeleton"], indent=2, ensure_ascii=False)
    revision_id = int(match.group(1))
    restored = rev_manager.restore_revision(revision_id)
    if restored is None:
        return "❌ גרסה לא נמצאה", json.dumps(deck_state["skeleton"], indent=2, ensure_ascii=False)
    deck_state["skeleton"] = restored
    full_json = json.dumps(restored, indent=2, ensure_ascii=False)
    return f"✅ שוחזר לגרסה {revision_id} — העריכה הבאה תיצור גרסה חדשה", full_json


def export_json():
    if deck_state["skeleton"] is None:
        return None
    output_path = "presentation_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(deck_state["skeleton"], f, indent=2, ensure_ascii=False)
    return output_path



def build_app():

    with gr.Blocks(
        title="כלי יצירת מצגות",
        theme=gr.themes.Soft(),
        css="""
        .rtl-text { direction: rtl; text-align: right; }

        .deck-preview { direction: rtl; text-align: right; }
        .preview-header {
            font-size: 18px; font-weight: bold; margin-bottom: 16px;
            padding: 8px 12px; background: #f0f4ff; border-radius: 8px;
            text-align: center;
        }
        .slides-container { display: flex; flex-direction: column; gap: 24px; }
        .slide-card {
            border: 2px solid #d0d5dd; border-radius: 12px;
            background: #4b5320; overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            aspect-ratio: 16 / 9; max-width: 720px; margin: 0 auto;
            display: flex; flex-direction: column;
        }
        .slide-title-bar {
            background: linear-gradient(135deg, #1e3a5f, #2d5f8a);
            color: white; padding: 20px 28px;
            font-size: 22px; font-weight: bold;
            text-align: right; direction: rtl;
        }
        .slide-body {
            padding: 20px 28px; flex: 1;
            direction: rtl; text-align: right;
            overflow-y: auto; font-size: 14px; line-height: 1.7;
        }
        .slide-obj-label {
            font-size: 12px; color: #131715; margin-top: 8px; margin-bottom: 2px;
            font-weight: bold;
        }
        .slide-bullets {
            margin: 4px 20px 12px 0; padding: 0;
            list-style-type: disc; direction: rtl;
        }
        .slide-bullets li { margin-bottom: 4px; }
        .slide-text { margin: 4px 0 12px 0; }
        .slide-empty { color: #999; font-style: italic; text-align: center; padding: 40px; }
        .slide-footer {
            background: #f7f8fa; padding: 6px 28px;
            font-size: 12px; color: #888;
            text-align: left; border-top: 1px solid #eee;
        }
        .preview-empty {
            text-align: center; color: #999; padding: 40px;
            font-size: 16px; direction: rtl;
        }

        /* Outline styles */
        .outline-container { display: flex; flex-direction: column; gap: 12px; }
        .outline-card {
            border: 2px solid #e0e7ff; border-radius: 10px;
            background: #4b5320; padding: 16px 24px;
            direction: rtl; text-align: right;
            max-width: 720px; margin: 0 auto; width: 100%;
        }
        .outline-num {
            font-size: 12px; color: #888; font-weight: bold; margin-bottom: 4px;
        }
        .outline-title {
            font-size: 18px; font-weight: bold; color: #1e3a5f; margin-bottom: 8px;
        }
        .outline-bullets {
            margin: 0 20px 0 0; padding: 0;
            list-style-type: circle; color: #444; font-size: 14px;
        }
        .outline-bullets li { margin-bottom: 4px; }
        .outline-placeholder {
            color: #aab; font-style: italic;
        }
        .outline-placeholder-warning {
            color: #c09030; font-style: italic;
        }
        .outline-desc {
            color: #556; font-size: 13px; line-height: 1.6;
            margin: 4px 0 0 0; direction: rtl;
        }
        .outline-topics-label {
            font-size: 12px; color: #555; margin-bottom: 2px; font-style: italic;
        }
        .outline-note {
            text-align: center; font-size: 13px; color: #666;
            margin-bottom: 12px; font-style: italic;
            max-width: 720px; margin: 0 auto 12px auto;
        }
        .outline-card-warning {
            border-color: #f0c040; background: #fffdf0;
        }
        .outline-assessment {
            background: #e8f4fd; border-radius: 8px; padding: 10px 16px;
            margin-bottom: 12px; direction: rtl; text-align: right;
            font-size: 14px; color: #1a5276; max-width: 720px; margin: 0 auto 12px auto;
        }
        .outline-warning {
            background: #fff3cd; border: 1px solid #f0c040; border-radius: 8px;
            padding: 10px 16px; margin-bottom: 12px;
            direction: rtl; text-align: right;
            font-size: 14px; color: #856404; max-width: 720px; margin: 0 auto 12px auto;
        }
        """
    ) as app:

        gr.Markdown("# 📊 כלי יצירת מצגות", elem_classes=["rtl-text"])

        # ── Tab 1: Generation ──
        with gr.Tab("🚀 יצירת מצגת"):
            with gr.Row():
                with gr.Column(scale=1):
                    template_file = gr.File(
                        label="📁 קובץ תבנית (JSON) — אופציונלי",
                        file_types=[".json"]
                    )
                    gr.Markdown(
                        "*ללא תבנית — המערכת תציע מבנה אוטומטי*",
                        elem_classes=["rtl-text"]
                    )

                with gr.Column(scale=2):
                    user_prompt_input = gr.Textbox(
                        label="הנחיית משתמש",
                        placeholder="לדוגמה: חקירת אירוע טיסת חירום בתאריך 12 במרץ 2025",
                        lines=3,
                        rtl=True
                    )
                    document_text_input = gr.Textbox(
                        label="טקסט מסמך (אופציונלי)",
                        placeholder="הדבק כאן טקסט ממסמך מקור...",
                        lines=5,
                        rtl=True
                    )
                    slide_count_input = gr.Dropdown(
                        label="מספר שקפים (אופציונלי)",
                        choices=["אוטומטי"] + [str(i) for i in range(1, 11)],
                        value="אוטומטי",
                        interactive=True
                    )

            generate_btn = gr.Button("🚀 צור מצגת", variant="primary", size="lg")
            generation_status = gr.Textbox(label="סטטוס", interactive=False, rtl=True)

            # Outline approval section (shown only for template-free)
            with gr.Group(visible=False) as outline_section:
                outline_preview = gr.HTML(value="")

                with gr.Row():
                    outline_edit_input = gr.Textbox(
                        label="עריכת מבנה (אופציונלי)",
                        placeholder='לדוגמה: "הוסף שקף על לוחות זמנים" או "הסר את שקף 3"',
                        lines=2,
                        rtl=True,
                        scale=3
                    )
                    outline_edit_btn = gr.Button("🔄 עדכן מבנה", variant="secondary", scale=1)

                outline_edit_status = gr.Textbox(label="סטטוס עריכת מבנה", interactive=False, rtl=True, visible=False)

                approve_btn = gr.Button("✅ אשר מבנה וצור מצגת", variant="primary", size="lg")

            # Preview + JSON
            gr.Markdown("### 👁️ תצוגה מקדימה", elem_classes=["rtl-text"])
            generation_preview = gr.HTML(
                value='<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>'
            )
            with gr.Accordion("📄 JSON מצגת", open=False):
                generation_json = gr.Code(label="JSON מצגת", language="json", lines=20)

        # ── Tab 2: Deck-Level Edit ──
        with gr.Tab("✏️ עריכת מצגת"):
            gr.Markdown(
                "### עריכה ברמת המצגת\n"
                "שוחח עם הסוכן לעריכות רחבות על כל המצגת.\n"
                'לדוגמה: "הפוך את כל המצגת לפורמלית יותר" '
                'או "קצר את כל השקפים"',
                elem_classes=["rtl-text"]
            )

            deck_chatbot = gr.Chatbot(
                label="צ'אט עריכת מצגת",
                height=350,
                type="messages",
                rtl=True
            )

            with gr.Row():
                deck_chat_input = gr.Textbox(
                    label="הנחיית עריכה",
                    placeholder="כתוב כאן מה לשנות במצגת...",
                    lines=2,
                    rtl=True,
                    scale=4
                )
                deck_send_btn = gr.Button("שלח", variant="primary", scale=1)

            gr.Markdown("### 👁️ תצוגה מקדימה", elem_classes=["rtl-text"])
            deck_edit_preview = gr.HTML(
                value='<div class="preview-empty">התצוגה תתעדכן לאחר עריכה</div>'
            )

            with gr.Accordion("📄 JSON מעודכן", open=False):
                deck_edit_json = gr.Code(label="JSON מעודכן", language="json", lines=15)

            gr.Markdown("---")
            gr.Markdown("### 📜 היסטוריית גרסאות", elem_classes=["rtl-text"])

            with gr.Row():
                revision_dropdown = gr.Dropdown(
                    label="בחר גרסה לשחזור",
                    choices=[],
                    interactive=True,
                    scale=3
                )
                restore_btn = gr.Button("⏪ שחזר גרסה", variant="secondary", scale=1)

            restore_status = gr.Textbox(label="סטטוס שחזור", interactive=False, rtl=True)

            gr.Markdown("---")
            with gr.Row():
                export_btn = gr.Button("💾 ייצוא JSON", variant="secondary")
                export_file = gr.File(label="קובץ לייצוא")

        # ── Tab 3: Slide-Level Edit ──
        with gr.Tab("🔍 עריכת שקף"):
            gr.Markdown(
                "### עריכה ברמת השקף\n"
                "בחר שקף ושוחח עם הסוכן על שינויים בשקף הנבחר בלבד.\n"
                'לדוגמה: "עדכן את Rectangle 2 עם תאריך האירוע" '
                'או "קצר את התוכן"',
                elem_classes=["rtl-text"]
            )

            slide_selector = gr.Dropdown(
                label="בחר שקף",
                choices=[],
                interactive=True
            )

            slide_preview = gr.Markdown(
                value="בחר שקף כדי לראות את התוכן שלו",
                elem_classes=["rtl-text"]
            )

            slide_chatbot = gr.Chatbot(
                label="צ'אט עריכת שקף",
                height=300,
                type="messages",
                rtl=True
            )

            with gr.Row():
                slide_chat_input = gr.Textbox(
                    label="הנחיית עריכה לשקף",
                    placeholder="כתוב כאן מה לשנות בשקף הנבחר...",
                    lines=2,
                    rtl=True,
                    scale=4
                )
                slide_send_btn = gr.Button("שלח", variant="primary", scale=1)

            slide_revision_dropdown = gr.Dropdown(
                label="📜 היסטוריית גרסאות",
                choices=[],
                interactive=False
            )

        # ── Event Bindings ──

        # Tab 1: Generation
        generate_btn.click(
            fn=handle_generate,
            inputs=[template_file, user_prompt_input, document_text_input, slide_count_input],
            outputs=[generation_status, generation_preview, generation_json,
                     outline_section, outline_preview]
        ).then(
            fn=lambda: gr.update(choices=get_slide_choices()),
            outputs=[slide_selector]
        )

        # Outline editing
        outline_edit_btn.click(
            fn=edit_outline,
            inputs=[outline_edit_input],
            outputs=[outline_edit_status, outline_preview]
        ).then(
            fn=lambda: "",
            outputs=[outline_edit_input]
        )

        # Outline approval
        approve_btn.click(
            fn=approve_outline,
            inputs=[],
            outputs=[generation_status, generation_preview, generation_json,
                     outline_section, outline_preview]
        ).then(
            fn=lambda: gr.update(choices=get_slide_choices()),
            outputs=[slide_selector]
        )

        # Tab 2: Deck-level edit
        deck_send_btn.click(
            fn=deck_chat_edit,
            inputs=[deck_chat_input, deck_chatbot],
            outputs=[deck_chatbot, deck_edit_preview, deck_edit_json, revision_dropdown]
        ).then(
            fn=lambda: ("", gr.update(choices=get_slide_choices())),
            outputs=[deck_chat_input, slide_selector]
        ).then(
            fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()),
            outputs=[slide_revision_dropdown]
        )

        deck_chat_input.submit(
            fn=deck_chat_edit,
            inputs=[deck_chat_input, deck_chatbot],
            outputs=[deck_chatbot, deck_edit_preview, deck_edit_json, revision_dropdown]
        ).then(
            fn=lambda: ("", gr.update(choices=get_slide_choices())),
            outputs=[deck_chat_input, slide_selector]
        ).then(
            fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()),
            outputs=[slide_revision_dropdown]
        )

        restore_btn.click(
            fn=restore_revision,
            inputs=[revision_dropdown],
            outputs=[restore_status, deck_edit_json]
        )

        export_btn.click(
            fn=export_json,
            inputs=[],
            outputs=[export_file]
        )

        # Tab 3: Slide-level edit
        slide_selector.change(
            fn=on_slide_selected,
            inputs=[slide_selector],
            outputs=[slide_preview]
        )

        slide_send_btn.click(
            fn=slide_chat_edit,
            inputs=[slide_chat_input, slide_selector, slide_chatbot],
            outputs=[slide_chatbot, slide_preview, slide_revision_dropdown]
        ).then(
            fn=lambda: "",
            outputs=[slide_chat_input]
        ).then(
            fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()),
            outputs=[revision_dropdown]
        )

        slide_chat_input.submit(
            fn=slide_chat_edit,
            inputs=[slide_chat_input, slide_selector, slide_chatbot],
            outputs=[slide_chatbot, slide_preview, slide_revision_dropdown]
        ).then(
            fn=lambda: "",
            outputs=[slide_chat_input]
        ).then(
            fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()),
            outputs=[revision_dropdown]
        )

    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(share=False)
