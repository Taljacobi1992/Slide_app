#import re
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
            template="""אתה בודק תוכן עבור מצגות מקצועיות. תפקידך למנוע הזיות ותוכן בדוי, תוך אישור תוכן לגיטימי.

התוכן שנוצר:
{generated_content}

═══ מקורות המידע המותרים ═══

הנחיית המשתמש:
{user_prompt}

מסמך מקור:
{document_text}

═══ הנחיות פורמט בלבד ═══

תיאור השקף: {slide_description}
תיאור האובייקט: {object_description}

═══════════════════════════

השאלה המרכזית: "האם התוכן סותר את המקורות או מכיל עובדות שלא קיימות בהם?"

אשר ✅ אם: התוכן מסכם/מנסח מחדש/מארגן מידע מהמקורות, או מסקנות סבירות הנגזרות מהמידע.
דחה ❌ אם: עובדות ספציפיות שלא במקורות, תוכן ריק, תוכן גנרי לחלוטין, או "לא סופק מספיק מידע" כשיש מידע רלוונטי.

החזר בדיוק בפורמט הזה (3 שורות):
VALID: כן/לא
REASON: סיבה קצרה
FEEDBACK: הנחיה לשיפור (או "אין" אם תקין)
"""
        )

    def validate(self, generated_content, user_prompt, slide_description, object_description, document_text):

        if not generated_content or not generated_content.strip():
            return {
                "is_valid": False,
                "reason": "התוכן שנוצר ריק",
                "feedback": "יש ליצור תוכן בפועל על בסיס מקורות המידע",
                "raw_response": "[PRE-CHECK: empty content rejected]"
            }

        formatted_prompt = self.validation_prompt.format(
            generated_content=generated_content,
            user_prompt=user_prompt,
            slide_description=slide_description,
            object_description=object_description,
            document_text=document_text or "לא סופק"
        )

        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": formatted_prompt}],
                temperature=0.1,
                max_tokens=300
            )
            result_text = response.choices[0].message.content or ""
            return self._parse_validation_response(result_text)

        except Exception as e:
            return {
                "is_valid": False,
                "reason": f"שגיאה בקריאה לסוכן הבדיקה: {str(e)}",
                "feedback": "נסה שוב",
                "raw_response": f"[API ERROR: {str(e)}]"
            }

    def _parse_validation_response(self, response_text: str) -> dict:
        result = {
            "is_valid": False,
            "reason": "",
            "feedback": "",
            "raw_response": response_text
        }

        if not response_text or not response_text.strip():
            result["reason"] = "תשובת הבדיקה ריקה"
            result["feedback"] = "נסה שוב"
            return result

        try:
            text = response_text.strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
            if text.endswith("```"):
                text = "\n".join(text.split("\n")[:-1])
            text = text.strip().replace("\\n", "\n")

            lines = text.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                line_upper = line.upper()

                if line_upper.startswith("VALID"):
                    value = line.split(":", 1)[-1].strip() if ":" in line else ""
                    result["is_valid"] = any(v in value for v in ("כן", "yes", "Yes", "כן.", "true", "True"))
                elif line_upper.startswith("REASON"):
                    value = line.split(":", 1)[-1].strip() if ":" in line else ""
                    if value:
                        result["reason"] = value
                elif line_upper.startswith("FEEDBACK"):
                    value = line.split(":", 1)[-1].strip() if ":" in line else ""
                    if value and value != "אין":
                        result["feedback"] = value

            if result["is_valid"] and not result["reason"]:
                result["reason"] = "תקין"
            if not result["reason"] and not result["is_valid"]:
                result["reason"] = "לא ניתן לפענח את תשובת הבדיקה"
                result["feedback"] = response_text[:300]

        except Exception as e:
            result["is_valid"] = False
            result["reason"] = f"שגיאה בפענוח: {str(e)}"
            result["feedback"] = response_text[:300] if response_text else "נסה שוב"

        return result


# ──────────────────────────────────────────────
#  Slide Agent (with validation chain)
# ──────────────────────────────────────────────

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

        # ── Simplified generation prompt ──
        # The generator's job is to WRITE content. Anti-hallucination is the validator's job.
        self.prompt_template = PromptTemplate(
            input_variables=[
                "user_prompt",
                "slide_description",
                "object_description",
                "document_text",
                "language_instruction",
                "validation_feedback"
            ],
            template="""אתה כותב תוכן עבור שקף במצגת מקצועית.

המשימה שלך: חלץ מידע רלוונטי מהמקורות וכתוב אותו בפורמט המתאים לשקף.

מקורות המידע:
---
הנחיית המשתמש: {user_prompt}

מסמך מקור:
{document_text}
---

שקף: {slide_description}
פורמט נדרש: {object_description}

{language_instruction}

{validation_feedback}

הנחיות:
- חלץ מידע רלוונטי מהמקורות למעלה וארגן אותו לפי הפורמט הנדרש.
- מותר לנסח מחדש, לסכם, ולארגן — זו המטרה שלך.
- אם המקורות לא מכילים מידע רלוונטי לשקף הזה, החזר בדיוק: "לא סופק מספיק מידע להצגת תוכן זה."
- אל תחזיר תשובה ריקה. תמיד החזר תוכן או את הודעת "לא סופק מספיק מידע".
- כתוב בעברית תקינה וברורה.

החזר רק את התוכן:
"""
        )

    def generate_slide(self, slide: dict, user_prompt: str, document_text: str = ""):
        """Generate content for all objects in a slide, with validation."""

        for obj in slide["slide_objects"]:

            if self._is_title_object(obj):
                obj["generated_content"] = self._generate_title(obj["object_name"])
                obj["validation_status"] = "skipped"
                continue

            # Skip generation if Structure Agent flagged no source content
            if obj.get("has_source_content") is False:
                obj["generated_content"] = ValidatorAgent.NO_INFO_MESSAGE
                obj["validation_status"] = "no_source_content"
                obj["validation_attempts"] = 0
                obj["validation_reason"] = "סומן על ידי סוכן המבנה כחסר מידע מספיק"
                obj["validation_feedback"] = ""
                obj["validation_raw"] = ""
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
            obj["validation_reason"] = result.get("reason", "")
            obj["validation_feedback"] = result.get("feedback", "")
            obj["validation_raw"] = result.get("raw_response", "")

        slide["generation_status"] = "completed"
        return slide

    def _generate_with_validation(
        self,
        slide_description: str,
        object_description: str,
        user_prompt: str,
        document_text: str
    ) -> dict:
        validation_feedback = ""
        total_attempts = 1 + self.max_retries
        last_reason = ""
        last_feedback = ""
        last_raw = ""

        for attempt in range(1, total_attempts + 1):

            content = self._generate_with_llm(
                slide_description=slide_description,
                object_description=object_description,
                user_prompt=user_prompt,
                document_text=document_text,
                validation_feedback=validation_feedback
            )

            # Reject empty content immediately
            if not content or not content.strip():
                last_reason = "התוכן שנוצר ריק"
                last_feedback = "יש ליצור תוכן בפועל על בסיס המקורות"
                last_raw = "[EMPTY CONTENT - skipped validation]"
                if attempt < total_attempts:
                    validation_feedback = (
                        "⚠️ ניסיון קודם נכשל — התוכן שהחזרת היה ריק.\n"
                        "חובה להחזיר תוכן. חלץ מידע מהמקורות, או אם אין מידע החזר: "
                        '"לא סופק מספיק מידע להצגת תוכן זה."'
                    )
                continue

            # Validate content
            validation = self.validator.validate(
                generated_content=content,
                user_prompt=user_prompt,
                slide_description=slide_description,
                object_description=object_description,
                document_text=document_text
            )

            last_reason = validation.get("reason", "")
            last_feedback = validation.get("feedback", "")
            last_raw = validation.get("raw_response", "")

            if validation["is_valid"]:
                return {
                    "content": content,
                    "status": "validated",
                    "attempts": attempt,
                    "reason": last_reason or "תקין",
                    "feedback": "",
                    "raw_response": last_raw
                }

            # Retry with feedback
            if attempt < total_attempts:
                reason_text = validation.get("reason", "לא צוינה סיבה")
                feedback_text = validation.get("feedback", "נסה לשפר את התוכן")
                validation_feedback = (
                    f"⚠️ ניסיון קודם נפסל. סיבה: {reason_text}\n"
                    f"הנחיה לשיפור: {feedback_text}\n"
                    f"תקן את התוכן בהתאם."
                )

        # All attempts exhausted
        return {
            "content": ValidatorAgent.NO_INFO_MESSAGE,
            "status": "failed_validation",
            "attempts": total_attempts,
            "reason": last_reason or "כל הניסיונות נכשלו",
            "feedback": last_feedback or "לא התקבל משוב מהבודק",
            "raw_response": last_raw
        }

    def _get_language_instruction(self):
        if self.language.lower() == "hebrew":
            return "כתוב בעברית בלבד."
        return "Generate output in the same language as the input."

    def _is_title_object(self, obj: dict) -> bool:
        name = obj["object_name"].lower()
        keywords = ["תת", "כותרת"]
        return any(word in name for word in keywords)

    def _generate_title(self, object_name: str) -> str:
        name = object_name.strip()
        for word in ["כותרת", "תת"]:
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
            document_text=document_text or "לא סופק",
            language_instruction=self._get_language_instruction(),
            validation_feedback=validation_feedback
        )

        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": formatted_prompt}],
                temperature=0.3,
                max_tokens=500
            )
            return response.choices[0].message.content or ""

        except Exception as e:
            print(f"[SlideAgent] LLM generation error: {e}")
            return ""
