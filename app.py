import json
import gradio as gr

from services.slide_agent import SlideAgent
from services.structure_agent import generate_outline, edit_outline, outline_to_skeleton
from services.edit_agent import (
    deck_chat_edit, slide_chat_edit, on_slide_selected,
    restore_revision, export_json
)
from utils.state import deck_state, get_slide_choices, detect_slide_count
from utils.revision_manager import RevisionManager
from ui.renderers import render_deck_preview, render_outline_html


#  Generation Handler

def handle_generate(file, user_prompt, document_text, slide_count_input):
    has_template = file is not None
    has_prompt = bool(user_prompt and user_prompt.strip())

    if not has_template and not has_prompt:
        return ("❌ יש להזין הנחיית משתמש כאשר לא נבחרה תבנית",
                '<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>',
                "{}", gr.update(visible=False), "")

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
            agent.generate_slide(slide=slide, user_prompt=user_prompt, document_text=document_text or "")

        rev_manager.save_revision(skeleton=skeleton, action="יצירה", description="יצירת מצגת ראשונית עם תבנית")
        return ("✅ המצגת נוצרה בהצלחה", render_deck_preview(skeleton),
                json.dumps(skeleton, indent=2, ensure_ascii=False), gr.update(visible=False), "")

    detected_count = detect_slide_count(user_prompt)
    if detected_count:
        slide_count = detected_count
    elif slide_count_input and slide_count_input != "אוטומטי" and str(slide_count_input).isdigit():
        slide_count = int(slide_count_input)
    else:
        slide_count = None

    deck_state["user_prompt"] = user_prompt
    deck_state["document_text"] = document_text or ""

    total_input_words = len(user_prompt.split()) + len((document_text or "").split())
    content_warning = ""
    if total_input_words < 20:
        content_warning = f"⚠️ שים לב: כמות המידע שסופקה מצומצמת ({total_input_words} מילים). מומלץ להוסיף מסמך מקור או להרחיב את ההנחיה.\n\n"

    try:
        outline = generate_outline(user_prompt, document_text, slide_count)
        deck_state["pending_outline"] = outline
        return (f"{content_warning}📋 מבנה מוצע עם {len(outline.get('slides', []))} שקפים — בדוק ואשר או ערוך",
                '<div class="preview-empty">אשר את המבנה המוצע כדי ליצור את המצגת</div>',
                "{}", gr.update(visible=True), render_outline_html(outline))
    except Exception as e:
        return (f"❌ שגיאה ביצירת מבנה: {str(e)}",
                '<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>',
                "{}", gr.update(visible=False), "")


def approve_outline():
    outline = deck_state.get("pending_outline")
    if outline is None:
        return ("❌ אין מבנה מוצע לאישור", '<div class="preview-empty">אין מצגת</div>',
                "{}", gr.update(visible=False), "")

    skeleton = outline_to_skeleton(outline)
    agent = SlideAgent(language="hebrew")
    rev_manager = RevisionManager()

    deck_state["skeleton"] = skeleton
    deck_state["agent"] = agent
    deck_state["revision_manager"] = rev_manager
    deck_state["pending_outline"] = None

    for slide in skeleton["slides"]:
        agent.generate_slide(slide=slide, user_prompt=deck_state.get("user_prompt", ""),
                             document_text=deck_state.get("document_text", ""))

    rev_manager.save_revision(skeleton=skeleton, action="יצירה", description="יצירת מצגת ממבנה מותאם")
    return ("✅ המצגת נוצרה בהצלחה ממבנה מותאם", render_deck_preview(skeleton),
            json.dumps(skeleton, indent=2, ensure_ascii=False), gr.update(visible=False), "")


#  CSS

CSS = """
.rtl-text { direction: rtl; text-align: right; }
.deck-preview { direction: rtl; text-align: right; }
.preview-header { font-size: 18px; font-weight: bold; margin-bottom: 16px; padding: 8px 12px; background: #f0f4ff; border-radius: 8px; text-align: center; }
.slides-container { display: flex; flex-direction: column; gap: 24px; }
.slide-card { border: 2px solid #d0d5dd; border-radius: 12px; background: #4B7340; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); aspect-ratio: 16 / 9; max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; }
.slide-title-bar { background: linear-gradient(135deg, #1e3a5f, #2d5f8a); color: white; padding: 20px 28px; font-size: 22px; font-weight: bold; text-align: right; direction: rtl; }
.slide-body { padding: 20px 28px; flex: 1; direction: rtl; text-align: right; overflow-y: auto; font-size: 14px; line-height: 1.7; }
.slide-obj-label { font-size: 12px; color: #667; margin-top: 8px; margin-bottom: 2px; font-weight: bold; }
.slide-bullets { margin: 4px 20px 12px 0; padding: 0; list-style-type: disc; direction: rtl; }
.slide-bullets li { margin-bottom: 4px; }
.slide-text { margin: 4px 0 12px 0; }
.slide-empty { color: #999; font-style: italic; text-align: center; padding: 40px; }
.slide-footer { background: #f7f8fa; padding: 6px 28px; font-size: 12px; color: #888; text-align: left; border-top: 1px solid #eee; }
.slide-key-statement { display: flex; align-items: center; justify-content: center; text-align: center; font-size: 24px; font-weight: bold; color: #1e3a5f; padding: 40px 28px; line-height: 1.5; direction: rtl; flex: 1; }
.slide-two-columns { display: flex; flex-direction: row-reverse; gap: 16px; direction: rtl; flex: 1; }
.slide-col-right, .slide-col-left { flex: 1; padding: 0 8px; }
.slide-col-right { border-left: 2px solid #e0e5ee; }
.slide-col-label { font-size: 13px; font-weight: bold; color: #2d5f8a; margin-bottom: 6px; }
.slide-section-header { background: linear-gradient(135deg, #1e3a5f, #2d5f8a); display: flex; flex-direction: column; justify-content: center; align-items: center; }
.slide-section-title { color: white; font-size: 28px; font-weight: bold; text-align: center; padding: 60px 28px; flex: 1; display: flex; align-items: center; }
.slide-section-header .slide-footer { background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
.preview-empty { text-align: center; color: #999; padding: 40px; font-size: 16px; direction: rtl; }
.outline-container { display: flex; flex-direction: column; gap: 12px; }
.outline-card { border: 2px solid #e0e7ff; border-radius: 10px; background: #fafbff; padding: 16px 24px; direction: rtl; text-align: right; max-width: 720px; margin: 0 auto; width: 100%; }
.outline-num { font-size: 12px; color: #888; font-weight: bold; margin-bottom: 4px; }
.outline-title { font-size: 18px; font-weight: bold; color: #1e3a5f; margin-bottom: 8px; }
.outline-placeholder { color: #aab; font-style: italic; }
.outline-placeholder-warning { color: #c09030; font-style: italic; }
.outline-desc { color: #556; font-size: 13px; line-height: 1.6; margin: 4px 0 0 0; direction: rtl; }
.outline-layout-badge { display: inline-block; font-size: 11px; color: #fff; background: #2d5f8a; border-radius: 12px; padding: 2px 10px; margin-bottom: 6px; }
.outline-columns { display: flex; flex-direction: row-reverse; gap: 12px; margin-top: 4px; }
.outline-col { flex: 1; direction: rtl; }
.outline-col-label { font-size: 12px; font-weight: bold; color: #2d5f8a; margin-bottom: 2px; }
.outline-col-divider { width: 1px; background: #d0d5dd; }
.outline-key-statement { font-size: 15px; font-weight: bold; color: #1e3a5f; text-align: center; margin: 8px 0 0 0; font-style: italic; }
.outline-card-warning { border-color: #f0c040; background: #fffdf0; }
.outline-warning { background: #fff3cd; border: 1px solid #f0c040; border-radius: 8px; padding: 10px 16px; margin-bottom: 12px; direction: rtl; text-align: right; font-size: 14px; color: #856404; max-width: 720px; margin: 0 auto 12px auto; }
"""


#  Gradio


def build_app():
    with gr.Blocks(title="כלי יצירת מצגות", theme=gr.themes.Soft(), css=CSS) as app:

        gr.Markdown("# 📊 כלי יצירת מצגות", elem_classes=["rtl-text"])

        with gr.Tab("🚀 יצירת מצגת"):
            with gr.Row():
                with gr.Column(scale=1):
                    template_file = gr.File(label="📁 קובץ תבנית (JSON) — אופציונלי", file_types=[".json"])
                    gr.Markdown("*ללא תבנית — המערכת תציע מבנה אוטומטי*", elem_classes=["rtl-text"])
                with gr.Column(scale=2):
                    user_prompt_input = gr.Textbox(label="הנחיית משתמש", lines=3, rtl=True)
                    document_text_input = gr.Textbox(label="טקסט מסמך (אופציונלי)", placeholder="הדבק כאן טקסט ממסמך מקור...", lines=5, rtl=True)
                    slide_count_input = gr.Dropdown(label="מספר שקפים (אופציונלי)", choices=["אוטומטי"] + [str(i) for i in range(1, 11)], value="אוטומטי", interactive=True)

            generate_btn = gr.Button("🚀 צור מצגת", variant="primary", size="lg")
            generation_status = gr.Textbox(label="סטטוס", interactive=False, rtl=True)

            with gr.Group(visible=False) as outline_section:
                outline_preview = gr.HTML(value="")
                with gr.Row():
                    outline_edit_input = gr.Textbox(label="עריכת מבנה (אופציונלי)", placeholder='לדוגמה: "הוסף שקף לקחים והמלצות "', lines=2, rtl=True, scale=3)
                    outline_edit_btn = gr.Button("🔄 עדכן מבנה", variant="secondary", scale=1)
                outline_edit_status = gr.Textbox(label="סטטוס עריכת מבנה", interactive=False, rtl=True, visible=False)
                approve_btn = gr.Button("✅ אשר מבנה וצור מצגת", variant="primary", size="lg")

            gr.Markdown("### 👁️ תצוגה מקדימה", elem_classes=["rtl-text"])
            generation_preview = gr.HTML(value='<div class="preview-empty">אין מצגת לתצוגה מקדימה</div>')
            with gr.Accordion("📄 JSON מצגת", open=False):
                generation_json = gr.Code(label="JSON מצגת", language="json", lines=20)

        with gr.Tab("✏️ עריכת מצגת"):
            gr.Markdown("### עריכה ברמת המצגת\nשוחח עם הסוכן לעריכות רחבות על כל המצגת.", elem_classes=["rtl-text"])
            deck_chatbot = gr.Chatbot(label="צ'אט עריכת מצגת", height=350, rtl=True)
            with gr.Row():
                deck_chat_input = gr.Textbox(label="הנחיית עריכה", placeholder="כתוב כאן מה לשנות במצגת...", lines=2, rtl=True, scale=4)
                deck_send_btn = gr.Button("שלח", variant="primary", scale=1)
            gr.Markdown("### 👁️ תצוגה מקדימה", elem_classes=["rtl-text"])
            deck_edit_preview = gr.HTML(value='<div class="preview-empty">התצוגה תתעדכן לאחר עריכה</div>')
            with gr.Accordion("📄 JSON מעודכן", open=False):
                deck_edit_json = gr.Code(label="JSON מעודכן", language="json", lines=15)
            gr.Markdown("---")
            gr.Markdown("### 📜 היסטוריית גרסאות", elem_classes=["rtl-text"])
            with gr.Row():
                revision_dropdown = gr.Dropdown(label="בחר גרסה לשחזור", choices=[], interactive=True, scale=3)
                restore_btn = gr.Button("⏪ שחזר גרסה", variant="secondary", scale=1)
            restore_status = gr.Textbox(label="סטטוס שחזור", interactive=False, rtl=True)
            gr.Markdown("---")
            with gr.Row():
                export_btn = gr.Button("💾 ייצוא JSON", variant="secondary")
                export_file = gr.File(label="קובץ לייצוא")

        with gr.Tab("🔍 עריכת שקף"):
            gr.Markdown("### עריכה ברמת השקף\nבחר שקף ושוחח עם הסוכן על שינויים בשקף הנבחר בלבד.", elem_classes=["rtl-text"])
            slide_selector = gr.Dropdown(label="בחר שקף", choices=[], interactive=True)
            slide_preview = gr.Markdown(value="בחר שקף כדי לראות את התוכן שלו", elem_classes=["rtl-text"])
            slide_chatbot = gr.Chatbot(label="צ'אט עריכת שקף", height=300, rtl=True)
            with gr.Row():
                slide_chat_input = gr.Textbox(label="הנחיית עריכה לשקף", placeholder="כתוב כאן מה לשנות בשקף הנבחר...", lines=2, rtl=True, scale=4)
                slide_send_btn = gr.Button("שלח", variant="primary", scale=1)
            slide_revision_dropdown = gr.Dropdown(label="📜 היסטוריית גרסאות", choices=[], interactive=False)

        # ── Event Bindings ──
        generate_btn.click(fn=handle_generate, inputs=[template_file, user_prompt_input, document_text_input, slide_count_input], outputs=[generation_status, generation_preview, generation_json, outline_section, outline_preview]).then(fn=lambda: gr.update(choices=get_slide_choices()), outputs=[slide_selector])
        outline_edit_btn.click(fn=edit_outline, inputs=[outline_edit_input], outputs=[outline_edit_status, outline_preview]).then(fn=lambda: "", outputs=[outline_edit_input])
        approve_btn.click(fn=approve_outline, inputs=[], outputs=[generation_status, generation_preview, generation_json, outline_section, outline_preview]).then(fn=lambda: gr.update(choices=get_slide_choices()), outputs=[slide_selector])

        deck_send_btn.click(fn=deck_chat_edit, inputs=[deck_chat_input, deck_chatbot], outputs=[deck_chatbot, deck_edit_preview, deck_edit_json, revision_dropdown]).then(fn=lambda: ("", gr.update(choices=get_slide_choices())), outputs=[deck_chat_input, slide_selector]).then(fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()), outputs=[slide_revision_dropdown])
        deck_chat_input.submit(fn=deck_chat_edit, inputs=[deck_chat_input, deck_chatbot], outputs=[deck_chatbot, deck_edit_preview, deck_edit_json, revision_dropdown]).then(fn=lambda: ("", gr.update(choices=get_slide_choices())), outputs=[deck_chat_input, slide_selector]).then(fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()), outputs=[slide_revision_dropdown])

        restore_btn.click(fn=restore_revision, inputs=[revision_dropdown], outputs=[restore_status, deck_edit_json])
        export_btn.click(fn=export_json, inputs=[], outputs=[export_file])

        slide_selector.change(fn=on_slide_selected, inputs=[slide_selector], outputs=[slide_preview])
        slide_send_btn.click(fn=slide_chat_edit, inputs=[slide_chat_input, slide_selector, slide_chatbot], outputs=[slide_chatbot, slide_preview, slide_revision_dropdown]).then(fn=lambda: "", outputs=[slide_chat_input]).then(fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()), outputs=[revision_dropdown])
        slide_chat_input.submit(fn=slide_chat_edit, inputs=[slide_chat_input, slide_selector, slide_chatbot], outputs=[slide_chatbot, slide_preview, slide_revision_dropdown]).then(fn=lambda: "", outputs=[slide_chat_input]).then(fn=lambda: gr.update(choices=deck_state["revision_manager"].get_revision_choices()), outputs=[revision_dropdown])

    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(share=False)
