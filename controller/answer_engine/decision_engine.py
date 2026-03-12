"""
Answer decision engine.

Integrates question matching, option matching, and conflict detection
to produce a final answer decision for each question.

Decision flow:
    1. Run question matcher (staged lookup)
    2. If cached: retrieve stored answer, match to current options
    3. If new: use AI answer, store question
    4. If conflict: raise conflict for operator intervention
    5. Return decision with the click target letter

Canonical Law 1 (Determinism): Same inputs produce same decisions.
Canonical Law 8 (Content matching): Options matched by text.
Canonical Law 9 (AI validation): Conflicts require operator input.
"""

from enum import Enum
from typing import Optional

from controller.ai_pipeline.response_parser import GrokResponse
from controller.answer_engine.option_matcher import match_option_by_content
from controller.answer_engine.conflict_handler import (
    check_ai_db_conflict,
    Conflict,
    ConflictType,
)
from controller.question_engine.question_matcher import (
    match_question,
    MatchResult,
    MatchSource,
)
from controller.question_engine.embedding_matcher import embedding_to_bytes
from controller.utils.logger import get_logger
from database.db_manager import DatabaseManager

logger = get_logger("decision_engine")


class DecisionOutcome(str, Enum):
    CLICK = "click"
    CONFLICT = "conflict"
    ERROR = "error"


class AnswerDecision:
    """Final answer decision for a question."""

    def __init__(
        self,
        outcome: DecisionOutcome,
        click_letter: Optional[str] = None,
        source: Optional[str] = None,
        conflict: Optional[Conflict] = None,
        error_message: Optional[str] = None,
        question_id: Optional[int] = None,
        match_result: Optional[MatchResult] = None,
    ) -> None:
        self.outcome = outcome
        self.click_letter = click_letter
        self.source = source
        self.conflict = conflict
        self.error_message = error_message
        self.question_id = question_id
        self.match_result = match_result


def decide_answer(
    db: DatabaseManager,
    test_id: int,
    grok_response: GrokResponse,
) -> AnswerDecision:
    """
    Determine the final answer action for a question.

    Args:
        db: Database manager.
        test_id: Active test ID.
        grok_response: Parsed and validated Grok response.

    Returns:
        AnswerDecision indicating what action to take.
    """
    options_dict = {
        "A": grok_response.options.A,
        "B": grok_response.options.B,
        "C": grok_response.options.C,
        "D": grok_response.options.D,
    }

    match = match_question(
        db=db,
        test_id=test_id,
        question_text=grok_response.question,
        options=options_dict,
    )

    if match.is_cached:
        logger.info(
            "Question found in DB (source=%s, question_id=%d)",
            match.source.value, match.question_record["question_id"],
        )

        db_answer = match.correct_answer

        conflict = check_ai_db_conflict(
            ai_answer_content=grok_response.answer_content,
            db_answer_content=db_answer,
            question_id=match.question_record["question_id"],
        )
        if conflict:
            return AnswerDecision(
                outcome=DecisionOutcome.CONFLICT,
                conflict=conflict,
                source=match.source.value,
                question_id=match.question_record["question_id"],
                match_result=match,
            )

        option_match = match_option_by_content(db_answer, options_dict)
        if not option_match.found:
            return AnswerDecision(
                outcome=DecisionOutcome.CONFLICT,
                conflict=Conflict(
                    conflict_type=ConflictType.NO_OPTION_MATCH,
                    message=f"Stored answer '{db_answer[:60]}' doesn't match any current option",
                    db_answer=db_answer,
                    question_id=match.question_record["question_id"],
                ),
                source=match.source.value,
                question_id=match.question_record["question_id"],
                match_result=match,
            )

        logger.info(
            "DB answer matched to option %s (confidence=%s)",
            option_match.matched_letter, option_match.confidence,
        )
        return AnswerDecision(
            outcome=DecisionOutcome.CLICK,
            click_letter=option_match.matched_letter,
            source=match.source.value,
            question_id=match.question_record["question_id"],
            match_result=match,
        )

    else:
        logger.info("New question — using AI answer: %s", grok_response.answer)

        question_id = db.store_question(
            test_id=test_id,
            canonical_text=match.canonical_text,
            sha256_hash=match.sha256_hash,
            simhash=match.simhash,
            embedding_vector=embedding_to_bytes(match.embedding),
            option_a=grok_response.options.A,
            option_b=grok_response.options.B,
            option_c=grok_response.options.C,
            option_d=grok_response.options.D,
            correct_answer=grok_response.answer_content,
            answer_letter=grok_response.answer,
        )

        return AnswerDecision(
            outcome=DecisionOutcome.CLICK,
            click_letter=grok_response.answer,
            source=MatchSource.AI_NEW.value,
            question_id=question_id,
            match_result=match,
        )
