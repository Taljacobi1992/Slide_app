import re
import os
from dotenv import load_dotenv
from langsmith import traceable
from huggingface_hub import InferenceClient
from langchain_core.prompts import PromptTemplate


load_dotenv()

client = InferenceClient(
    provider="groq",
    api_key=os.getenv("HF_TOKEN")
)

model_name = "openai/gpt-oss-120b"


#  Validator agent

class ValidatorAgent:
 
    NO_INFO_MESSAGE = "לא סופק מספיק מידע להצגת תוכן זה."

    @traceable(name="Validator Agent")
    def __init__(self, model_name=model_name, max_retries=2):
        self.model_name = model_name
        self.max_retries = max_retries

        self.validation_prompt = PromptTemplate(
            input_variables=[
                "generated_content",
                "user_prompt",
                "slide_description",
                "object_description",
                "document_text"
            ],
            template="""אתה בודק תוכן עבור מצגות מקצועיות. תפקידך למנוע הזיות (hallucinations) ותוכן בדוי, אך גם לוודא שמידע אמיתי שסופק אכן מנוצל.

התוכן שנוצר:
{generated_content}

═══ מקורות המידע המותרים (מקור האמת) ═══

הנחיית המשתמש:
{user_prompt}

מסמך מקור:
{document_text}

═══ הנחיות פורמט בלבד (לא מקור מידע!) ═══

תיאור השקף:
{slide_description}

תיאור האובייקט (פורמט בלבד):
{object_description}

═══════════════════════════════════════════

כללי בדיקה קריטיים:

הבדיקה המרכזית — סיווג התוכן לשלוש קטגוריות:

א. חילוץ ועיבוד מידע (תקין ✅):
   התוכן מבוסס על מידע מהנחיית המשתמש או מהמסמך, גם אם הוא מנוסח מחדש, מסוכם, מאורגן מחדש, או מותאם לפורמט השקף. זו בדיוק המטרה.

ב. הזיה / תוכן בדוי (לא תקין ❌):
   התוכן מכיל עובדות, פרטים, תאריכים, שמות, או מידע שלא מופיע בהנחיית המשתמש או במסמך.
   שים לב במיוחד:
   - תוכן שנשאב מ"תיאור האובייקט" — זו הזיה! תיאור האובייקט הוא הנחיית פורמט בלבד.
   - תוכן גנרי שנשמע מקצועי אבל לא מבוסס על מידע ספציפי מהמקורות — זו הזיה.

ג. סירוב מוצדק (תקין ✅):
   אם התוכן הוא "לא סופק מספיק מידע להצגת תוכן זה." — זה תקין רק אם באמת אין מידע רלוונטי במקורות.
   אבל: אם המשתמש או המסמך סיפקו מידע רלוונטי והתוכן בכל זאת אומר "לא סופק מספיק מידע" — זה לא תקין. יש לחלץ את המידע הקיים.

בדיקות נוספות:
4. שפה — האם התוכן בעברית תקינה בלבד?
5. חזרות — האם יש חזרות מיותרות?
6. פורמט — האם הפורמט מתאים?

החזר תשובה בפורמט הבא בלבד:
VALID: כן/לא
REASON: [סיבה קצרה אם לא תקין]
FEEDBACK: [הנחיה ספציפית לשיפור אם לא תקין]
"""
        )

    def validate(
        self,
        generated_content: str,
        user_prompt: str,
        slide_description: str,
        object_description: str,
        document_text: str
    ) -> dict:
        """
        Validates generated content.
        Returns: {"is_valid": bool, "reason": str, "feedback": str}
        """
        formatted_prompt = self.validation_prompt.format(
            generated_content=generated_content,
            user_prompt=user_prompt,
            slide_description=slide_description,
            object_description=object_description,
            document_text=document_text or "לא סופק"
        )

        response = client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "user", "content": formatted_prompt}
            ],
            temperature=0.1,
            max_tokens=300
        )

        result_text = response.choices[0].message.content
        return self._parse_validation_response(result_text)

    def _parse_validation_response(self, response_text: str) -> dict:
        """Parse the structured validation response."""
        result = {
            "is_valid": False,
            "reason": "",
            "feedback": ""
        }

        try:
            lines = response_text.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("VALID:"):
                    value = line.replace("VALID:", "").strip()
                    result["is_valid"] = value in ("כן", "yes", "Yes", "כן.")
                elif line.startswith("REASON:"):
                    result["reason"] = line.replace("REASON:", "").strip()
                elif line.startswith("FEEDBACK:"):
                    result["feedback"] = line.replace("FEEDBACK:", "").strip()
        except Exception:
            # If parsing fails, treat as invalid to be safe
            result["is_valid"] = False
            result["reason"] = "שגיאה בפענוח תוצאת הבדיקה"
            result["feedback"] = "נסה שוב"

        return result



#  Slide agent

class SlideAgent:

    @traceable(name="Slide Agent")
    def __init__(self, model_name=model_name, language="hebrew", max_retries=2):
        self.language = language
        self.model_name = model_name
        self.max_retries = max_retries
        self.client = InferenceClient(
            model=model_name,
            token=os.getenv("HF_TOKEN")
        )
        self.validator = ValidatorAgent(
            model_name=model_name,
            max_retries=max_retries
        )

        self.prompt_template = PromptTemplate(
            input_variables=[
                "user_prompt",
                "slide_description",
                "object_description",
                "document_text",
                "language_instruction",
                "validation_feedback"
            ],
            template="""אתה כותב תוכן מקצועי עבור שקף של מצגת.

═══ מקורות מידע (מקור האמת — רק מכאן ניתן לשאוב עובדות) ═══

הנחיית המשתמש:
{user_prompt}

מסמך מקור:
{document_text}

═══ הנחיות פורמט בלבד (אין לשאוב מכאן עובדות או תוכן!) ═══

מטרת השקף:
{slide_description}

מבנה האובייקט (הנחיית פורמט בלבד — לא מקור מידע!):
{object_description}

═══════════════════════════════════════════════════════

{language_instruction}

{validation_feedback}

כללי כתיבה קריטיים:
1. מקור האמת היחיד הוא הנחיית המשתמש והמסמך. כל עובדה, פרט, או תוכן חייב להגיע משם.
2. "מבנה האובייקט" מתאר את הפורמט והמבנה הרצוי בלבד — הוא לא מקור מידע!
   - אם כתוב שם "בתאריך X בוצע משימה Y" — זו דוגמה לפורמט, לא תוכן לשימוש.
   - אין להפוך את דוגמאות הפורמט לתוכן אמיתי.
3. אם המסמך או הנחיית המשתמש מכילים מידע רלוונטי — חובה לחלץ אותו, לסכם, לארגן ולהתאים אותו למבנה הנדרש. זו המטרה העיקרית שלך.
   - מותר ורצוי לנסח מחדש, לסכם, לשנות סדר, ולהתאים את המידע לפורמט השקף.
   - זה לא נחשב המצאה — זו עבודתך.
4. אם הנחיית המשתמש או המסמך לא מכילים מספיק מידע למלא את השדה — החזר בדיוק: "לא סופק מספיק מידע להצגת תוכן זה."
5. אין להמציא עובדות, תאריכים, שמות, מיקומים, או פרטים שלא מופיעים במקורות המידע.
6. אין ליצור תוכן גנרי או כללי שנשמע מקצועי אבל לא מבוסס על מידע אמיתי.
7. יש לכתוב בעברית תקינה וברורה.
8. אם נדרש פירוט ויש מספיק מידע — כתוב בבולטים קצרים.

החזר רק את התוכן.
"""
        )

    def generate_slide(self, slide: dict, user_prompt: str, document_text: str = ""):
        """Generate content for all objects in a slide, with validation."""

        for obj in slide["slide_objects"]:

            if self._is_title_object(obj):
                obj["generated_content"] = self._generate_title(obj["object_name"])
                obj["validation_status"] = "skipped"
                continue

            result = self._generate_with_validation(
                slide_description=slide["slide_description"],
                object_description=obj["object_description"],
                user_prompt=user_prompt,
                document_text=document_text
            )

            obj["generated_content"] = result["content"]
            obj["validation_status"] = result["status"]
            obj["validation_attempts"] = result["attempts"]

        slide["generation_status"] = "completed"
        return slide

    def _generate_with_validation(
        self,
        slide_description: str,
        object_description: str,
        user_prompt: str,
        document_text: str
    ) -> dict:
        """
        Generate content with validation loop.
        Returns: {"content": str, "status": str, "attempts": int}
        """
        validation_feedback = ""  # no feedback on first attempt
        total_attempts = 1 + self.max_retries  # 1 initial + retries

        for attempt in range(1, total_attempts + 1):

            content = self._generate_with_llm(
                slide_description=slide_description,
                object_description=object_description,
                user_prompt=user_prompt,
                document_text=document_text,
                validation_feedback=validation_feedback
            )

            validation = self.validator.validate(
                generated_content=content,
                user_prompt=user_prompt,
                slide_description=slide_description,
                object_description=object_description,
                document_text=document_text
            )

            if validation["is_valid"]:
                return {
                    "content": content,
                    "status": "validated",
                    "attempts": attempt
                }

            if attempt < total_attempts:
                validation_feedback = (
                    f"⚠️ ניסיון קודם נפסל. סיבה: {validation['reason']}\n"
                    f"הנחיה לשיפור: {validation['feedback']}\n"
                    f"אנא תקן את התוכן בהתאם."
                )

        return {
            "content": ValidatorAgent.NO_INFO_MESSAGE,
            "status": "failed_validation",
            "attempts": total_attempts
        }

    def _get_language_instruction(self):
        if self.language.lower() == "hebrew":
            return "כל הפלט חייב להיות בעברית בלבד. אין להשתמש באנגלית."
        return "Generate output in the same language as the input."

    def _is_title_object(self, obj: dict) -> bool:
        name = obj["object_name"].lower()
        keywords = ["תת", "כותרת"]
        return any(word in name for word in keywords)

    def _generate_title(self, object_name: str) -> str:
        name = object_name.strip()

        replacements = [
            "כותרת",
            "תת",
        ]

        for word in replacements:
            name = name.replace(word, "")

        return " ".join(name.split())

    def _generate_with_llm(
        self,
        slide_description: str,
        object_description: str,
        user_prompt: str,
        document_text: str,
        validation_feedback: str = ""
    ) -> str:

        formatted_prompt = self.prompt_template.format(
            user_prompt=user_prompt,
            slide_description=slide_description,
            object_description=object_description,
            document_text=document_text or "None",
            language_instruction=self._get_language_instruction(),
            validation_feedback=validation_feedback
        )

        response = client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "user", "content": formatted_prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        return response.choices[0].message.content
