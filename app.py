import re
import os
import json
import copy
import gradio as gr
from datetime import datetime
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from slide_agent import SlideAgent

#theme = gr.Theme.from_hub("gstaff/xkcd")
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

        # Enforce max revisions — remove oldest (keep first revision + latest N-1)
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
        for rev in reversed(self.revisions):  # newest first
            rid = rev["revision_id"]
            ts = rev["timestamp"]
            action = rev["action"]
            desc = rev["description"]
            choices.append(f"[גרסה {rid}] {ts} — {action}: {desc}")
        return choices

    def get_latest_id(self) -> int:
        return self.current_revision_id

    def reset(self):
        """Clear all revisions."""
        self.revisions = []
        self.current_revision_id = 0

  #  Edit agent


deck_state = {
    "skeleton": None,
    "agent": None,
    "revision_manager": RevisionManager()
}


def load_and_generate(file, user_prompt, document_text):
    """Load template and generate presentation in one step."""
    if file is None:
        return "❌ לא נבחר קובץ תבנית", "{}"

    content = file.read().decode("utf-8") if hasattr(file, "read") else open(file, "r", encoding="utf-8").read()
    skeleton = json.loads(content)

    agent = SlideAgent(language="hebrew")
    rev_manager = RevisionManager()  # fresh history for new deck

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

    # Save initial revision
    rev_manager.save_revision(
        skeleton=skeleton,
        action="יצירה",
        description="יצירת מצגת ראשונית"
    )

    full_json = json.dumps(skeleton, indent=2, ensure_ascii=False)
    return "✅ המצגת נוצרה בהצלחה", full_json


def chat_edit(user_message, chat_history):
    """Process a free-text edit instruction via the agent."""
    if deck_state["skeleton"] is None:
        chat_history = chat_history or []
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": "❌ יש ליצור מצגת קודם בלשונית 'יצירת מצגת'."})
        return chat_history, json.dumps({}, indent=2, ensure_ascii=False), gr.update(choices=[])

    agent = deck_state["agent"]
    skeleton = deck_state["skeleton"]
    rev_manager = deck_state["revision_manager"]

    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_message})

    # Build context for the edit agent
    deck_json = json.dumps(skeleton, indent=2, ensure_ascii=False)

    edit_prompt = f"""אתה עורך מצגות מקצועי. המשתמש מבקש לערוך תוכן במצגת.

המצגת הנוכחית (JSON):
{deck_json}

ההנחיה המקורית של המשתמש:
{deck_state.get("user_prompt", "")}

מסמך מקור:
{deck_state.get("document_text", "לא סופק")}

בקשת העריכה:
{user_message}

חשוב — מבנה המצגת:
- כל שקף מזוהה לפי "slide_num" (מספר שלם: 1, 2, 3...).
- כל אובייקט בשקף מזוהה לפי:
  - "object_id" — מזהה טכני כמו "Rectangle 2", "Title 1". שים לב: object_id יכול לחזור על עצמו בין שקפים שונים!
  - "object_name" — שם תיאורי ייחודי כמו "תוכן רקע האירוע".
- לכן, כדי לזהות אובייקט באופן חד-משמעי, יש לציין גם slide_num וגם object_id או object_name.

עליך:
1. לזהות את האובייקט/ים שהמשתמש מתייחס אליהם.
2. לבצע את השינוי המבוקש על התוכן הקיים (generated_content). אם התוכן הקיים ריק או "לא סופק מספיק מידע" — צור תוכן חדש לפי ההנחיה.
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


    response = InferenceClient(
        provider="groq",
        api_key=os.getenv("HF_TOKEN")
    ).chat.completions.create(
        model=agent.model_name,
        messages=[{"role": "user", "content": edit_prompt}],
        temperature=0.2,
        max_tokens=1000
    )

    raw_response = response.choices[0].message.content

    # Parse the edit response
    try:
        # Clean potential markdown code fences
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
        if cleaned.endswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[:-1])

        edit_data = json.loads(cleaned)

        applied_count = 0
        for edit in edit_data.get("edits", []):
            edit_slide_num = str(edit.get("slide_num", ""))
            edit_object_id = edit.get("object_id", "")
            edit_object_name = edit.get("object_name", "")
            new_content = edit.get("new_content", "")

            matched = False

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

            # Pass 2: If slide_num didn't match, try object_name across all slides (it's unique)
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

        summary = edit_data.get("summary", "")
        if applied_count > 0:
            # Save revision after successful edit
            rev_manager.save_revision(
                skeleton=skeleton,
                action="עריכה",
                description=summary
            )
            rev_id = rev_manager.get_latest_id()
            assistant_msg = f"✅ {summary} ({applied_count} אובייקטים עודכנו) — גרסה {rev_id}"
        else:
            # Show full debug info
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



def restore_revision(revision_selection):
    """Restore the deck to a previous revision (navigation only, no new revision created)."""
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

    # Update current state — no new revision created
    deck_state["skeleton"] = restored

    full_json = json.dumps(restored, indent=2, ensure_ascii=False)

    return f"✅ שוחזר לגרסה {revision_id} — העריכה הבאה תיצור גרסה חדשה", full_json


def export_json():
    """Export the current deck state as a JSON file."""
    if deck_state["skeleton"] is None:
        return None

    output_path = "presentation_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(deck_state["skeleton"], f, indent=2, ensure_ascii=False)

    return output_path


# Gradio

def build_app():

    with gr.Blocks(
        title="כלי יצירת מצגות",
        theme=gr.themes.Soft(),
        css="""
        .rtl-text { direction: rtl; text-align: right; }
        """
    ) as app:

        gr.Markdown("כלי יצירת מצגות", elem_classes=["rtl-text"])

        # ── Tab 1: Generation ──
        with gr.Tab("יצירת מצגת"):
            with gr.Row():
                with gr.Column(scale=1):
                    template_file = gr.File(
                        label="קובץ תבנית (JSON)",
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
                        placeholder="הדבק כאן טקסט ממסמך מקור...",
                        lines=5,
                        rtl=True
                    )

            generate_btn = gr.Button("צור מצגת", variant="primary", size="lg")
            generation_status = gr.Textbox(label="סטטוס", interactive=False, rtl=True)
            generation_json = gr.Code(label="JSON מצגת", language="json", lines=20)

        # ── Tab 2: Chat Edit ──
        with gr.Tab(" עריכה"):
            gr.Markdown()

            chatbot = gr.Chatbot(
                label="צ'אט עריכה",
                height=400,
                type="messages",
                rtl=True
            )

            with gr.Row():
                chat_input = gr.Textbox(
                    label="הנחיית עריכה",
                    placeholder="כתוב כאן מה לשנות...",
                    lines=2,
                    rtl=True,
                    scale=4
                )
                send_btn = gr.Button("שלח", variant="primary", scale=1)

            edit_json = gr.Code(label="JSON מעודכן", language="json", lines=20)

            # ── Revision History Section ──
            gr.Markdown("---")
            gr.Markdown("### היסטוריית גרסאות", elem_classes=["rtl-text"])

            with gr.Row():
                revision_dropdown = gr.Dropdown(
                    label="בחר גרסה לשחזור",
                    choices=[],
                    interactive=True,
                    scale=3
                )
                restore_btn = gr.Button(" שחזר גרסה", variant="secondary", scale=1)

            restore_status = gr.Textbox(label="סטטוס שחזור", interactive=False, rtl=True)

            gr.Markdown("---")

            with gr.Row():
                export_btn = gr.Button("ייצוא JSON", variant="secondary")
                export_file = gr.File(label="קובץ לייצוא")

        # ── Event Bindings ──

        generate_btn.click(
            fn=load_and_generate,
            inputs=[template_file, user_prompt_input, document_text_input],
            outputs=[generation_status, generation_json]
        )

        send_btn.click(
            fn=chat_edit,
            inputs=[chat_input, chatbot],
            outputs=[chatbot, edit_json, revision_dropdown]
        ).then(
            fn=lambda: "",
            outputs=[chat_input]
        )

        chat_input.submit(
            fn=chat_edit,
            inputs=[chat_input, chatbot],
            outputs=[chatbot, edit_json, revision_dropdown]
        ).then(
            fn=lambda: "",
            outputs=[chat_input]
        )

        restore_btn.click(
            fn=restore_revision,
            inputs=[revision_dropdown],
            outputs=[restore_status, edit_json]
        )

        export_btn.click(
            fn=export_json,
            inputs=[],
            outputs=[export_file]
        )

    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(share=False)
