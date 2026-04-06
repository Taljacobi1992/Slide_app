def build_structure_prompt(user_prompt, document_text, count_instruction, count_rule):
    return f"""אתה מתכנן מבנה מצגות מקצועי ויצירתי. תפקידך להציע מבנה (structure) בלבד — לא תוכן סופי.

═══ מקורות מידע ═══

הנחיית המשתמש:
{user_prompt}

מסמך מקור:
{document_text or "לא סופק"}

═══════════════════

{count_instruction}

סוגי שקפים זמינים (layout):
- "title_only" — שקף כותרת בלבד, ללא תוכן. לשימוש בשקף פתיחה בלבד.
- "title_bullets" — כותרת + רשימת נקודות. לשימוש בתוכן כללי, פירוט, רשימות.
- "title_text" — כותרת + פסקת טקסט רציפה. לשימוש בהקשר, רקע, תיאור נרטיבי.
- "title_two_columns" — כותרת + שתי עמודות (שמאל וימין). לשימוש בהשוואות, לפני/אחרי, יתרונות/חסרונות.
- "title_key_statement" — כותרת + משפט מפתח אחד גדול. לשימוש בתובנה מרכזית, מספר מרכזי, ציטוט חשוב.
- "section_header" — כותרת מפרידה בין חלקים. לשימוש בין חלקים שונים של המצגת.

עבור כל שקף, הצע:
- כותרת (title) — כותרת קצרה וברורה
- layout — אחד מהסוגים הזמינים
- topics — תיאורי נושאים בלבד (לא תוכן סופי). בהתאם ל-layout:
  - title_only / section_header: רשימה ריקה []
  - title_bullets / title_text: 2-4 נושאים
  - title_two_columns: אובייקט עם "right" ו-"left", כל אחד עם 1-3 נושאים + תווית (label)
  - title_key_statement: רשימה עם נושא אחד בלבד
- has_content (true/false)

כללים:
1. הנושאים מתארים מה השקף יכסה — לא מה הוא יגיד. כותרות נושא, לא משפטי תוכן.
2. אין לכלול עובדות, תאריכים, שמות, או פרטים ספציפיים.
3. אם אין מספיק מידע לשקף — סמן has_content: false.
4. בחר layout מתאים לתוכן — אל תשתמש רק ב-title_bullets! מצגת מגוונת יותר מעניינת יותר.
{count_rule}
7. השקף הראשון תמיד title_only.
8. השקף האחרון יהיה סיכום/המלצות (אם יש מספיק מידע).
9. סדר הגיוני. הכל בעברית.

החזר JSON בלבד:

{{
  "preset_name": "מבנה מותאם",
  "content_assessment": "הערכה קצרה",
  "slides": [
    {{
      "slide_num": 1,
      "title": "כותרת המצגת",
      "layout": "title_only",
      "topics": [],
      "has_content": true
    }},
    {{
      "slide_num": 2,
      "title": "רקע והקשר",
      "layout": "title_text",
      "topics": ["הקשר היסטורי", "מצב נוכחי"],
      "has_content": true
    }},
    {{
      "slide_num": 3,
      "title": "השוואת מצב",
      "layout": "title_two_columns",
      "topics": {{
        "right": {{ "label": "לפני", "topics": ["מצב קודם", "אתגרים"] }},
        "left": {{ "label": "אחרי", "topics": ["מצב חדש", "שיפורים"] }}
      }},
      "has_content": true
    }},
    {{
      "slide_num": 4,
      "title": "תובנה מרכזית",
      "layout": "title_key_statement",
      "topics": ["הממצא המרכזי של החקירה"],
      "has_content": true
    }},
    {{
      "slide_num": 5,
      "title": "פירוט ממצאים",
      "layout": "title_bullets",
      "topics": ["ממצא ראשון", "ממצא שני", "ממצא שלישי"],
      "has_content": true
    }}
  ]
}}
"""


def build_outline_edit_prompt(outline_json, edit_instruction):
    return f"""אתה עורך מבנה מצגות. המשתמש מבקש לשנות את המבנה המוצע.

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


LAYOUT_LIST_SECTION = """סוגי Layout זמינים:
- "title_only" — כותרת בלבד
- "title_bullets" — כותרת + רשימת נקודות
- "title_text" — כותרת + פסקת טקסט רציפה
- "title_two_columns" — כותרת + שתי עמודות (ימין ושמאל)
- "title_key_statement" — כותרת + משפט מפתח אחד
- "section_header" — כותרת מפרידה בין חלקים"""

EDIT_RULES_SECTION = """כללי עריכה קריטיים:
1. בצע אך ורק את השינוי שהמשתמש ביקש — לא יותר ולא פחות.
2. אם המשתמש מבקש להוסיף מידע ספציפי — הוסף בדיוק את מה שנאמר. אל תמציא פרטים נוספים.
3. אם המשתמש מבקש לשנות סגנון — שנה את הסגנון בלבד, שמור על העובדות הקיימות.
4. אל תמציא עובדות, תאריכים, שמות, או מידע שלא מופיע במקורות.
5. כל התוכן חייב להיות בעברית תקינה.
6. חובה לשמור על הפורמט שמוגדר ב-object_description של כל אובייקט.
7. אם המשתמש מבקש לשנות layout של שקף — השתמש ב-layout_changes."""

EDIT_RESPONSE_FORMAT = """{{
  "edits": [
    {{
      "slide_num": {slide_num_example},
      "object_id": "Content 1",
      "object_name": "תוכן השקף",
      "new_content": "התוכן החדש או המעודכן"
    }}
  ],
  "layout_changes": [
    {{
      "slide_num": {slide_num_example},
      "new_layout": "title_two_columns"
    }}
  ],
  "summary": "תיאור קצר של מה שנעשה"
}}

הערות:
- אם אין שינוי layout, החזר "layout_changes": [].
- אם אין שינוי תוכן, החזר "edits": [].
- שינוי layout ימחק את התוכן הקיים ויצור אובייקטים חדשים — אין צורך לספק תוכן חדש ב-edits עבור שקף שמשנה layout."""


def build_deck_edit_prompt(deck_json, user_prompt, document_text, user_message):
    return f"""אתה עורך מצגות מקצועי. המשתמש מבקש לערוך תוכן במצגת.

המצגת הנוכחית (JSON):
{deck_json}

═══ מקורות מידע (מקור האמת) ═══

ההנחיה המקורית של המשתמש:
{user_prompt}

מסמך מקור:
{document_text or "לא סופק"}

בקשת העריכה:
{user_message}

═══════════════════════════════════

חשוב — מבנה המצגת:
- כל שקף מזוהה לפי "slide_num" (מספר שלם: 1, 2, 3...).
- כל שקף מכיל "slide_layout" שקובע את מבנה השקף.
- כל אובייקט בשקף מזוהה לפי:
  - "object_id" — מזהה טכני כמו "Content 1", "Key Statement", "Content Right".
  - "object_name" — שם תיאורי.

{LAYOUT_LIST_SECTION}

{EDIT_RULES_SECTION}

עליך:
1. לזהות אם הבקשה היא שינוי תוכן, שינוי layout, או שניהם.
2. לקרוא את ה-object_description של האובייקט כדי להבין את הפורמט הנדרש.
3. לבצע את השינוי המבוקש תוך שמירה על הפורמט.
4. להחזיר תשובה בפורמט JSON בלבד, ללא טקסט נוסף:

{EDIT_RESPONSE_FORMAT.format(slide_num_example=2)}

אם לא הצלחת לזהות את האובייקט — החזר:
{{
  "edits": [],
  "layout_changes": [],
  "summary": "לא הצלחתי לזהות את האובייקט. אנא ציין מספר שקף (slide_num) ושם אובייקט (object_name)."
}}
"""


def build_slide_edit_prompt(slide_json, slide_num, slide_layout, user_prompt, document_text, user_message, obj_list_str):
    return f"""אתה עורך מצגות מקצועי. המשתמש מבקש לערוך תוכן בשקף ספציפי.

השקף הנוכחי (JSON):
{slide_json}

═══ מקורות מידע (מקור האמת) ═══

ההנחיה המקורית של המשתמש:
{user_prompt}

מסמך מקור:
{document_text or "לא סופק"}

בקשת העריכה:
{user_message}

═══════════════════════════════════

חשוב — מבנה השקף:
- השקף הוא שקף מספר {slide_num}.
- ה-layout הנוכחי של השקף: {slide_layout}
- כל אובייקט בשקף מזוהה לפי:
  - "object_id" — מזהה טכני כמו "Content 1", "Key Statement", "Content Right".
  - "object_name" — שם תיאורי.

{LAYOUT_LIST_SECTION}

{EDIT_RULES_SECTION}

עליך:
1. לזהות אם הבקשה היא שינוי תוכן, שינוי layout, או שניהם.
2. לקרוא את ה-object_description של האובייקט כדי להבין את הפורמט הנדרש.
3. לבצע את השינוי המבוקש תוך שמירה על הפורמט.
4. להחזיר תשובה בפורמט JSON בלבד, ללא טקסט נוסף:

{EDIT_RESPONSE_FORMAT.format(slide_num_example=slide_num)}

אם לא הצלחת לזהות את האובייקט — החזר:
{{
  "edits": [],
  "layout_changes": [],
  "summary": "לא הצלחתי לזהות את האובייקט. האובייקטים הקיימים בשקף הם: {obj_list_str}"
}}
"""