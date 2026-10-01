"""Conservative, auditable source-to-translation review contract."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


FACT_TYPES = {"person", "action", "object", "number", "time", "polarity",
              "uncertainty", "cause", "other"}

_FACT = {"type": "object", "properties": {
    "span": {"type": "string"}, "type": {"type": "string", "enum": sorted(FACT_TYPES)}},
    "required": ["span", "type"], "additionalProperties": False}
_TRANSLATED_FACT = {"type": "object", "properties": {
    "span": {"type": "string"}, "type": {"type": "string", "enum": sorted(FACT_TYPES)},
    "source_span": {"type": "string"}},
    "required": ["span", "type", "source_span"], "additionalProperties": False}
ALIGNMENT_SCHEMA = {"type": "object", "properties": {
    "source_facts": {"type": "array", "items": _FACT},
    "translation_facts": {"type": "array", "items": _TRANSLATED_FACT},
    "unsupported_additions": {"type": "array", "items": {"type": "string"}},
    "missing_facts": {"type": "array", "items": {"type": "string"}},
    **{key: {"type": "boolean"} for key in ("polarity_mismatch", "number_mismatch",
                                              "entity_mismatch", "modality_mismatch")}},
    "required": ["source_facts", "translation_facts", "unsupported_additions", "missing_facts",
                 "polarity_mismatch", "number_mismatch", "entity_mismatch", "modality_mismatch"],
    "additionalProperties": False}


@dataclass(frozen=True)
class AlignmentReview:
    status: str
    issues: tuple[str, ...] = ()


def parse_alignment(raw: str, source: str, translation: str) -> AlignmentReview:
    """Treat missing or malformed evidence as PENDING, never as approval."""
    try:
        match = re.search(r"\{.*\}", raw, re.S)
        payload = json.loads(match.group() if match else raw)
        source_facts = payload["source_facts"]
        translated_facts = payload["translation_facts"]
        additions = payload["unsupported_additions"]
        omissions = payload["missing_facts"]
        flags = [payload[key] for key in ("polarity_mismatch", "number_mismatch",
                                          "entity_mismatch", "modality_mismatch")]
        if (not isinstance(source_facts, list) or not isinstance(translated_facts, list)
                or not isinstance(additions, list) or not isinstance(omissions, list)
                or not all(type(flag) is bool for flag in flags)
                or len(source_facts) > 16 or len(translated_facts) > 16
                or not source_facts or not translated_facts):
            return AlignmentReview("PENDING", ("incomplete_alignment",))
        for fact in source_facts:
            if (not isinstance(fact, dict) or fact.get("type") not in FACT_TYPES
                    or not isinstance(fact.get("span"), str) or not fact["span"].strip()
                    or fact["span"] not in source):
                return AlignmentReview("PENDING", ("invalid_source_evidence",))
        for fact in translated_facts:
            if (not isinstance(fact, dict) or fact.get("type") not in FACT_TYPES
                    or not isinstance(fact.get("span"), str) or not fact["span"].strip()
                    or fact["span"] not in translation
                    or not isinstance(fact.get("source_span"), str)
                    or not fact["source_span"].strip()
                    or fact["source_span"] not in source):
                return AlignmentReview("PENDING", ("invalid_translation_evidence",))
            if len(re.findall(r"[，。；！？,.!?]", fact["span"])) > 1:
                return AlignmentReview("PENDING", ("broad_translation_evidence",))
        clauses = [part.strip() for part in re.split(r"[，。；！？,.!?]+", translation) if part.strip()]
        for clause in clauses:
            if not any(fact["span"] in clause or clause in fact["span"]
                       for fact in translated_facts):
                return AlignmentReview("PENDING", ("uncovered_translation_clause",))
        if len(clauses) > len(source_facts) + 1:
            return AlignmentReview("PENDING", ("extra_translation_clauses",))
        if not all(isinstance(item, str) for item in additions + omissions):
            return AlignmentReview("PENDING", ("invalid_issue_list",))
        issues = tuple((["unsupported_addition"] if additions else [])
                       + (["missing_fact"] if omissions else [])
                       + [name for name, value in zip(("polarity", "number", "entity", "modality"), flags)
                          if value])
        return AlignmentReview("RETRY" if issues else "PASS", issues)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return AlignmentReview("PENDING", ("malformed_alignment",))
