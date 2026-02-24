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
    """Manages in-memory revision history for a presentation deck."""

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



deck_state = {
    "skeleton": None,
    "agent": None,
    "revision_manager": RevisionManager()
}



def get_slide_choices():
    """Build dropdown choices for slide selection."""
    if deck_state["skeleton"] is None:
        return []
    choices = []
    for slide in deck_state["skeleton"].get("slides", []):
        num = slide.get("slide_num", "?")
        desc = slide.get("slide_description", "ללא תיאור")
        choices.append(f"[שקף {num}] {desc}")
    return choices


def parse_slide_num_from_selection(selection: str) -> str | None:
    """Extract slide_num from dropdown selection string."""
    match = re.match(r"\[שקף (.+?)\]", selection)
    return match.group(1) if match else None


def get_slide_by_num(slide_num: str) -> dict | None:
    """Find a slide in the skeleton by slide_num."""
    if deck_state["skeleton"] is None:
        return None
    for slide in deck_state["skeleton"]["slides"]:
        if str(slide.get("slide_num", "")) == slide_num:
            return slide
    return None


def format_slide_preview(slide: dict) -> str:
    """Format a slide's objects as a readable preview."""
    lines = []
    lines.append(f"**שקף {slide.get('slide_num')}:** {slide.get('slide_description', '')}")
    lines.append(f"**סטטוס:** {slide.get('generation_status', 'ממתין')}")
    lines.append("")

    for obj in slide.get("slide_objects", []):
        obj_id = obj.get("object_id", "?")
        obj_name = obj.get("object_name", "?")
        status = obj.get("validation_status", "לא נוצר")
        content = obj.get("generated_content", "")

        icon = {"validated": "", "skipped": "⏭", "manual_fix": "",
                "edited_by_agent": "", "failed_validation": ""}.get(status, "")

        lines.append(f"---")
        lines.append(f"{icon} **{obj_id}** — {obj_name}")
        lines.append(f"סטטוס: {status}")
        lines.append(f"תוכן:")
        lines.append(f"```\n{content or '(ריק)'}\n```")

    return "\n".join(lines)


def apply_edits_to_skeleton(edit_data: dict, scope_slide_num: str = None) -> int:
    """
    Apply edits from LLM response to the skeleton.
    If scope_slide_num is provided, only apply to that slide.
    Returns number of applied edits.
    """
    skeleton = deck_state["skeleton"]
    applied_count = 0

    for edit in edit_data.get("edits", []):
        edit_slide_num = str(edit.get("slide_num", ""))
        edit_object_id = edit.get("object_id", "")
        edit_object_name = edit.get("object_name", "")
        new_content = edit.get("new_content", "")

        matched = False

        # If scoped to a slide, override the slide_num
        if scope_slide_num:
            edit_slide_num = scope_slide_num

        # Pass 1: Match by slide_num + (object_id or object_name)
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

        # Pass 2: Fallback — object_name across all slides (it's unique)
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
    """Call the LLM for edit operations."""
    from huggingface_hub import InferenceClient
    import os

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


def parse_llm_json(raw_response: str) -> dict:
    """Parse JSON from LLM response, handling markdown fences."""
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
    if cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[:-1])
    return json.loads(cleaned)



def load_and_generate(file, user_prompt, document_text):
    """Load template and generate presentation in one step."""
    if file is None:
        return "❌ לא נבחר קובץ תבנית", "{}"

    content = file.read().decode("utf-8") if hasattr(file, "read") else open(file, "r", encoding="utf-8").read()
    skeleton = json.loads(content)

    agent = SlideAgent(language="hebrew")
    rev_manager = RevisionManager()

    deck_state["skeleton"] = skeleton
    deck_state["agent"] = agent
    deck_state["user_prompt"] = user_prompt
    deck_state["document_text"] = document_text or ""
    deck_state["revision_manager"] = rev_manager

    for slide in skeleton["slides"]:
        agent.generate_slide(
            slide=slide,
            user_prompt=user_prompt,
            document_text=document_text or ""
        )

    rev_manager.save_revision(
        skeleton=skeleton,
        action="יצירה",
        description="יצירת מצגת ראשונית"
    )

    full_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
    return "✅ המצגת נוצרה בהצלחה", full_json


#  Deck-Level Chat Edit

def deck_chat_edit(user_message, chat_history):
    """Process a free-text edit instruction across the entire deck."""
    if deck_state["skeleton"] is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש ליצור מצגת קודם בלשונית 'יצירת מצגת'."})
        return chat_history, json.dumps({}, indent=2, ensure_ascii=False), gr.update(choices=[])

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
- לכן, כדי לזהות אובייקט באופן חד-משמעי, יש לציין גם slide_num וגם object_id או object_name.

כללי עריכה קריטיים:
1. בצע אך ורק את השינוי שהמשתמש ביקש — לא יותר ולא פחות.
2. אם המשתמש מבקש להוסיף מידע ספציפי (כמו תאריך, מיקום, שם) — הוסף בדיוק את מה שנאמר. אל תמציא פרטים נוספים.
3. אם המשתמש מבקש לשנות סגנון (קצר, פורמלי, וכו') — שנה את הסגנון בלבד, שמור על העובדות הקיימות.
4. אל תמציא עובדות, תאריכים, שמות, או מידע שלא מופיע בהנחיית המשתמש, במסמך המקור, או בבקשת העריכה.
5. אל תרחיב את התוכן מעבר למה שנדרש. אם המשתמש אמר "הוסף את התאריך מרץ 2025" — הוסף רק את התאריך, אל תכתוב פסקה שלמה.
6. כל התוכן חייב להיות בעברית תקינה.

עליך:
1. לזהות את האובייקט/ים שהמשתמש מתייחס אליהם.
2. לבצע את השינוי המבוקש על התוכן הקיים (generated_content). אם התוכן הקיים ריק או "לא סופק מספיק מידע" — צור תוכן חדש רק על בסיס המידע שסופק.
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
    revision_choices = rev_manager.get_revision_choices()

    return chat_history, full_json, gr.update(choices=revision_choices)


#  Slide-Level Chat Edit

def on_slide_selected(slide_selection):
    """When a slide is selected, show its preview."""
    if not slide_selection or deck_state["skeleton"] is None:
        return "בחר שקף כדי לראות את התוכן שלו"

    slide_num = parse_slide_num_from_selection(slide_selection)
    slide = get_slide_by_num(slide_num)

    if slide is None:
        return "❌ שקף לא נמצא"

    return format_slide_preview(slide)


def slide_chat_edit(user_message, slide_selection, chat_history):
    """Process an edit scoped to a specific slide."""
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

    # Only send this slide's JSON — smaller, focused context
    slide_json = json.dumps(slide, indent=2, ensure_ascii=False)

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
- המשתמש עשוי להתייחס לאובייקט לפי object_id, object_name, או תיאור כללי.

כללי עריכה קריטיים:
1. בצע אך ורק את השינוי שהמשתמש ביקש — לא יותר ולא פחות.
2. אם המשתמש מבקש להוסיף מידע ספציפי (כמו תאריך, מיקום, שם) — הוסף בדיוק את מה שנאמר. אל תמציא פרטים נוספים.
3. אם המשתמש מבקש לשנות סגנון (קצר, פורמלי, וכו') — שנה את הסגנון בלבד, שמור על העובדות הקיימות.
4. אל תמציא עובדות, תאריכים, שמות, או מידע שלא מופיע בהנחיית המשתמש, במסמך המקור, או בבקשת העריכה.
5. אל תרחיב את התוכן מעבר למה שנדרש. אם המשתמש אמר "הוסף את התאריך מרץ 2025" — הוסף רק את התאריך, אל תכתוב פסקה שלמה.
6. כל התוכן חייב להיות בעברית תקינה.

עליך:
1. לזהות את האובייקט/ים שהמשתמש מתייחס אליהם בתוך השקף הזה בלבד.
2. לבצע את השינוי המבוקש על התוכן הקיים (generated_content). אם התוכן הקיים ריק או "לא סופק מספיק מידע" — צור תוכן חדש רק על בסיס המידע שסופק.
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
  "summary": "לא הצלחתי לזהות את האובייקט. האובייקטים הקיימים בשקף הם: {', '.join(o.get('object_id', '') + ' (' + o.get('object_name', '') + ')' for o in slide.get('slide_objects', []))}"
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

    # Refresh slide preview
    updated_slide = get_slide_by_num(slide_num)
    preview = format_slide_preview(updated_slide) if updated_slide else ""
    revision_choices = rev_manager.get_revision_choices()

    return chat_history, preview, gr.update(choices=revision_choices)


#  Revision Management

def restore_revision(revision_selection):
    """Restore the deck to a previous revision (navigation only)."""
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


#  Export

def export_json():
    """Export the current deck state as a JSON file."""
    if deck_state["skeleton"] is None:
        return None

    output_path = "presentation_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(deck_state["skeleton"], f, indent=2, ensure_ascii=False)

    return output_path

#  Gradio

def build_app():

    with gr.Blocks(
        title="כלי יצירת מצגות",
        theme=gr.themes.Soft(),
        css="""
        .rtl-text { direction: rtl; text-align: right; }
        """
    ) as app:

        gr.Markdown("# 📊 כלי יצירת מצגות", elem_classes=["rtl-text"])

        # ── Tab 1: Generation ──
        with gr.Tab("🚀 יצירת מצגת"):
            with gr.Row():
                with gr.Column(scale=1):
                    template_file = gr.File(
                        label="📁 קובץ תבנית (JSON)",
                        file_types=[".json"]
                    )

                with gr.Column(scale=2):
                    user_prompt_input = gr.Textbox(
                        label="הנחיית משתמש",
                        lines=3,
                        rtl=True
                    )
                    document_text_input = gr.Textbox(
                        label="טקסט מסמך (אופציונלי)",
                        lines=5,
                        rtl=True
                    )

            generate_btn = gr.Button("🚀 צור מצגת", variant="primary", size="lg")
            generation_status = gr.Textbox(label="סטטוס", interactive=False, rtl=True)
            generation_json = gr.Code(label="JSON מצגת", language="json", lines=20)

        # ── Tab 2: Deck-Level Edit ──
        with gr.Tab("✏️ עריכת מצגת"):
            gr.Markdown()

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

            deck_edit_json = gr.Code(label="JSON מעודכן", language="json", lines=15)

            # ── Revision History ──
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
            gr.Markdown()

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

            # Revision dropdown shared reference for slide edits
            slide_revision_dropdown = gr.Dropdown(
                label="📜 היסטוריית גרסאות",
                choices=[],
                interactive=False  # display only, restore from deck tab
            )

        # ── Event Bindings ──

        # Tab 1: Generation
        generate_btn.click(
            fn=load_and_generate,
            inputs=[template_file, user_prompt_input, document_text_input],
            outputs=[generation_status, generation_json]
        ).then(
            fn=lambda: gr.update(choices=get_slide_choices()),
            outputs=[slide_selector]
        )

        # Tab 2: Deck-level edit
        deck_send_btn.click(
            fn=deck_chat_edit,
            inputs=[deck_chat_input, deck_chatbot],
            outputs=[deck_chatbot, deck_edit_json, revision_dropdown]
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
            outputs=[deck_chatbot, deck_edit_json, revision_dropdown]
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
