from langchain_core.prompts import PromptTemplate
from utils.llm import call_llm
from config import settings
from concurrent.futures import ThreadPoolExecutor, as_completed


#  Validator Agent

class ValidatorAgent:
    """Validates generated slide content against original user inputs"""

    def __init__(self) -> None:
        self.validation_prompt: PromptTemplate = PromptTemplate(
            input_variables=[
                "generated_content", "user_prompt", "slide_description",
                "object_description", "document_text",
            ],
            template="""אתה בודק תוכן מצגות. \
תפקידך למנוע הזיות ותוכן בדוי, תוך אישור תוכן לגיטימי.

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
""",
        )

    def validate(
        self,
        generated_content: str,
        user_prompt: str,
        slide_description: str,
        object_description: str,
        document_text: str,
    ) -> dict:
        """Validate generated content against sources, return result dict."""
        empty_check: dict | None = self._check_empty_content(generated_content)
        if empty_check is not None:
            return empty_check

        formatted_prompt: str = self.validation_prompt.format(
            generated_content=generated_content,
            user_prompt=user_prompt,
            slide_description=slide_description,
            object_description=object_description,
            document_text=document_text or "לא סופק",
        )

        try:
            result_text: str = call_llm(formatted_prompt, role="validation")
            return self._parse_validation_response(result_text)
        except Exception as e:
            return {
                "is_valid": False,
                "reason": f"שגיאה בקריאה לסוכן הבדיקה: {str(e)}",
                "feedback": "נסה שוב",
                "raw_response": f"[API ERROR: {str(e)}]",
            }

    @staticmethod
    def _check_empty_content(content: str) -> dict | None:
        """Return a failure dict if content is empty, else None."""
        if not content or not content.strip():
            return {
                "is_valid": False,
                "reason": "התוכן שנוצר ריק",
                "feedback": "יש ליצור תוכן בפועל על בסיס מקורות המידע",
                "raw_response": "[PRE-CHECK: empty content rejected]",
            }
        return None

    def _parse_validation_response(self, response_text: str) -> dict:
        """Parse the 3-line VALID/REASON/FEEDBACK format from the validator LLM."""
        result: dict = {
            "is_valid": False,
            "reason": "",
            "feedback": "",
            "raw_response": response_text,
        }

        if not response_text or not response_text.strip():
            result["reason"] = "תשובת הבדיקה ריקה"
            result["feedback"] = "נסה שוב"
            return result

        try:
            text: str = self._strip_markdown_fences(response_text)
            result = self._extract_fields_from_lines(text, result)
        except Exception as e:
            result["is_valid"] = False
            result["reason"] = f"שגיאה בפענוח: {str(e)}"
            result["feedback"] = response_text[:300] if response_text else "נסה שוב"

        return result

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Remove optional markdown code fences and unescape newlines."""
        text = text.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])
        return text.strip().replace("\\n", "\n")

    @staticmethod
    def _extract_fields_from_lines(text: str, result: dict) -> dict:
        """Parse VALID / REASON / FEEDBACK lines into result dict."""
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            line_upper: str = line.upper()

            if line_upper.startswith("VALID"):
                value: str = line.split(":", 1)[-1].strip() if ":" in line else ""
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
            result["feedback"] = text[:300]

        return result


#  Slide Agent

class SlideAgent:
    """Generates slide content with an LLM and validates via ValidatorAgent."""
    def __init__(self, language: str = "hebrew", max_retries: int = settings.settings.max_validation_retries) -> None:
        self.language: str = language
        self.max_retries: int = max_retries
        self.validator: ValidatorAgent = ValidatorAgent()

        self.prompt_template: PromptTemplate = PromptTemplate(
            input_variables=[
                "user_prompt", "slide_description", "object_description",
                "document_text", "language_instruction", "validation_feedback",
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
""",
        )


    def generate_slide(self, slide: dict, user_prompt: str, document_text: str = "") -> dict:
        """Generate content for every object in a slide."""
        for obj in slide["slide_objects"]:
            self._process_single_object(obj, slide["slide_description"], user_prompt, document_text)
        slide["generation_status"] = "completed"
        return slide
    


    def generate_all_slides(self, slides: list[dict], user_prompt: str, document_text: str, max_workers: int = 4) -> None:
        """Generate content for all slides in parallel."""
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.generate_slide, slide=slide, user_prompt=user_prompt, document_text=document_text): slide
                for slide in slides
            }
            for future in as_completed(futures):
                future.result()

    
    def regenerate_pending_objects(self, slide: dict, user_prompt: str, document_text: str) -> None:
        """Regenerate only objects marked as pending_regeneration in a slide."""
        for obj in slide.get("slide_objects", []):
            if obj.get("validation_status") == "pending_regeneration":
                self._process_single_object(
                obj, slide["slide_description"], user_prompt, document_text
            )

    # ── Object-Level Processing ──

    def _process_single_object(
        self, obj: dict, slide_description: str, user_prompt: str, document_text: str
    ) -> None:
        """Route a single slide object to the right generation strategy."""
        if self._is_title_object(obj):
            self._fill_title_object(obj)
            return

        if obj.get("has_source_content") is False:
            self._fill_no_source_object(obj)
            return

        self._fill_content_object(obj, slide_description, user_prompt, document_text)

    def _fill_title_object(self, obj: dict) -> None:
        """Populate a title object by extracting text from its name."""
        obj["generated_content"] = self._generate_title(obj["object_name"])
        obj["validation_status"] = "skipped"

    @staticmethod
    def _fill_no_source_object(obj: dict) -> None:
        """Mark an object as having no source content available."""
        obj["generated_content"] = settings.settings.no_info_message
        obj["validation_status"] = "no_source_content"
        obj["validation_attempts"] = 0
        obj["validation_reason"] = "סומן על ידי סוכן המבנה כחסר מידע מספיק"
        obj["validation_feedback"] = ""
        obj["validation_raw"] = ""

    def _fill_content_object(
        self, obj: dict, slide_description: str, user_prompt: str, document_text: str
    ) -> None:
        """Generate and validate content, then store results on the object."""
        result: dict = self._generate_with_validation(
            slide_description=slide_description,
            object_description=obj["object_description"],
            user_prompt=user_prompt,
            document_text=document_text,
        )
        obj["generated_content"] = result["content"]
        obj["validation_status"] = result["status"]
        obj["validation_attempts"] = result["attempts"]
        obj["validation_reason"] = result.get("reason", "")
        obj["validation_feedback"] = result.get("feedback", "")
        obj["validation_raw"] = result.get("raw_response", "")

    # ── Generation + Validation Loop ──

    def _generate_with_validation(
        self,
        slide_description: str,
        object_description: str,
        user_prompt: str,
        document_text: str,
    ) -> dict:
        """Try generating content up to max_retries+1 times, validating each attempt."""
        validation_feedback: str = ""
        total_attempts: int = 1 + self.max_retries
        last_reason: str = ""
        last_feedback: str = ""
        last_raw: str = ""

        for attempt in range(1, total_attempts + 1):
            content: str = self._generate_with_llm(
                slide_description, object_description,
                user_prompt, document_text, validation_feedback,
            )

            if not content or not content.strip():
                last_reason, last_feedback, last_raw = self._handle_empty_attempt()
                if attempt < total_attempts:
                    validation_feedback = self._empty_content_feedback()
                continue

            validation: dict = self.validator.validate(
                generated_content=content,
                user_prompt=user_prompt,
                slide_description=slide_description,
                object_description=object_description,
                document_text=document_text,
            )

            last_reason = validation.get("reason", "")
            last_feedback = validation.get("feedback", "")
            last_raw = validation.get("raw_response", "")

            if validation["is_valid"]:
                return self._success_result(content, attempt, last_reason, last_raw)

            if attempt < total_attempts:
                validation_feedback = self._build_retry_feedback(validation)

        return self._failure_result(total_attempts, last_reason, last_feedback, last_raw)

    # ── Validation-Loop Helpers ──

    @staticmethod
    def _handle_empty_attempt() -> tuple[str, str, str]:
        """Return reason/feedback/raw for an empty generation attempt."""
        return (
            "התוכן שנוצר ריק",
            "יש ליצור תוכן בפועל על בסיס המקורות",
            "[EMPTY CONTENT - skipped validation]",
        )

    @staticmethod
    def _empty_content_feedback() -> str:
        """Build feedback string for retrying after empty content."""
        return (
            "⚠️ ניסיון קודם נכשל — התוכן שהחזרת היה ריק.\n"
            "חובה להחזיר תוכן. "
            'חלץ מידע מהמקורות, או אם אין מידע החזר: '
            '"לא סופק מספיק מידע להצגת תוכן זה."'
        )

    @staticmethod
    def _build_retry_feedback(validation: dict) -> str:
        """Build feedback string from a failed validation result."""
        reason_text: str = validation.get("reason", "לא צוינה סיבה")
        feedback_text: str = validation.get("feedback", "נסה לשפר את התוכן")
        return (
            f"⚠️ ניסיון קודם נפסל. סיבה: {reason_text}\n"
            f"הנחיה לשיפור: {feedback_text}\nתקן את התוכן בהתאם."
        )

    @staticmethod
    def _success_result(content: str, attempt: int, reason: str, raw: str) -> dict:
        """Build the result dict for a successful validation."""
        return {
            "content": content,
            "status": "validated",
            "attempts": attempt,
            "reason": reason or "תקין",
            "feedback": "",
            "raw_response": raw,
        }

    @staticmethod
    def _failure_result(total_attempts: int, reason: str, feedback: str, raw: str) -> dict:
        """Build the result dict when all validation attempts are exhausted."""
        return {
            "content": settings.settings.no_info_message,
            "status": "failed_validation",
            "attempts": total_attempts,
            "reason": reason or "כל הניסיונות נכשלו",
            "feedback": feedback or "לא התקבל משוב מהבודק",
            "raw_response": raw,
        }

    # ── LLM Interaction ──

    def _generate_with_llm(
        self,
        slide_description: str,
        object_description: str,
        user_prompt: str,
        document_text: str,
        validation_feedback: str = "",
    ) -> str:
        """Format the prompt and call the generation LLM."""
        formatted_prompt: str = self.prompt_template.format(
            user_prompt=user_prompt,
            slide_description=slide_description,
            object_description=object_description,
            document_text=document_text or "לא סופק",
            language_instruction=self._get_language_instruction(),
            validation_feedback=validation_feedback,
        )
        return call_llm(formatted_prompt, role="generation")

    # ── Utilities ──

    def _get_language_instruction(self) -> str:
        """Return a language instruction string based on the configured language."""
        if self.language.lower() == "hebrew":
            return "כתוב בעברית בלבד."
        return "Generate output in the same language as the input."

    @staticmethod
    def _is_title_object(obj: dict) -> bool:
        """Check whether a slide object is a title (not content)."""
        name: str = obj["object_name"].lower()
        return any(word in name for word in ["תת", "כותרת"])

    @staticmethod
    def _generate_title(object_name: str) -> str:
        """Extract clean title text from an object name string."""
        name: str = object_name.strip()
        for word in ["כותרת", "תת"]:
            name = name.replace(word, "")
        return " ".join(name.split())
