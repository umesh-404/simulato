"""
AI vs Database conflict handler.

When the AI's suggested answer differs from the stored database answer,
the system must pause and request operator intervention
(Canonical Law 9 — AI Response Validation).

This module detects conflicts and produces alert payloads.
"""

from typing import Optional

from controller.utils.logger import get_logger

logger = get_logger("conflict_handler")


class ConflictType:
    AI_DB_MISMATCH = "AI_DB_MISMATCH"
    NO_OPTION_MATCH = "NO_OPTION_MATCH"
    AI_PARSE_FAILURE = "AI_PARSE_FAILURE"


class Conflict:
    """Represents a detected conflict requiring operator intervention."""

    def __init__(
        self,
        conflict_type: str,
        message: str,
        ai_answer: Optional[str] = None,
        db_answer: Optional[str] = None,
        question_id: Optional[int] = None,
    ) -> None:
        self.conflict_type = conflict_type
        self.message = message
        self.ai_answer = ai_answer
        self.db_answer = db_answer
        self.question_id = question_id

    def to_alert_payload(self) -> dict:
        return {
            "alert_type": self.conflict_type,
            "message": self.message,
            "ai_answer": self.ai_answer,
            "db_answer": self.db_answer,
            "question_id": self.question_id,
        }


def check_ai_db_conflict(
    ai_answer_content: str,
    db_answer_content: str,
    question_id: int,
) -> Optional[Conflict]:
    """
    Check whether the AI answer conflicts with the stored database answer.

    Uses normalized comparison. If they differ, returns a Conflict
    that must trigger an alert (Canonical Law 9).

    Returns None if no conflict.
    """
    from controller.utils.text_normalizer import normalize_for_matching

    norm_ai = normalize_for_matching(ai_answer_content)
    norm_db = normalize_for_matching(db_answer_content)

    if norm_ai == norm_db:
        logger.debug("AI/DB answers agree for question_id=%d", question_id)
        return None

    logger.warning(
        "AI/DB CONFLICT for question_id=%d: ai='%s' vs db='%s'",
        question_id, ai_answer_content[:60], db_answer_content[:60],
    )
    return Conflict(
        conflict_type=ConflictType.AI_DB_MISMATCH,
        message=(
            f"AI answer conflicts with database answer for question {question_id}. "
            f"AI says: '{ai_answer_content[:80]}'. "
            f"Database says: '{db_answer_content[:80]}'."
        ),
        ai_answer=ai_answer_content,
        db_answer=db_answer_content,
        question_id=question_id,
    )
