"""LLM guardrails - input and output rails around Trezo's LLM calls.

#120. The LLM-using agents (market sentiment) feed UNTRUSTED text -
news headlines written by third parties - into a language model. A
hostile headline could attempt a prompt injection. These rails are the
safety layer:

  - input rail  : cap the length of untrusted text and neutralise
                  injection-style phrasing before it reaches the model;
  - output rail : the model's reply must parse to a fixed, known set of
                  values - anything else is rejected, and the caller
                  falls back to the deterministic keyword path.

This is a lightweight, inspectable guardrails layer. Adopting the full
NeMo Guardrails library (its Colang rail config plus the dependency) is
a heavier follow-up; the rails here enforce the same intent - the model
can neither be steered by the news text nor return anything unexpected.
"""

from __future__ import annotations

from typing import Optional

# Phrases a prompt-injection attempt in untrusted text tends to use.
INJECTION_MARKERS = (
    "ignore previous", "ignore the above", "ignore all", "disregard",
    "system prompt", "you are now", "new instructions", "act as",
    "jailbreak", "forget everything", "override", "</item>", "<|",
    "assistant:", "system:",
)

MAX_INPUT_CHARS = 600

SENTIMENT_LABELS = {"positive", "negative", "neutral"}
EVENT_TYPES = {"earnings", "m_and_a", "guidance", "leadership", "legal",
               "analyst", "product", "general"}
SEVERITIES = {"low", "medium", "high"}


def sanitize_input(text: str) -> str:
    """Input rail: cap length, and neutralise injection-style phrasing in
    untrusted text before it reaches the model."""
    t = (text or "").strip()
    if len(t) > MAX_INPUT_CHARS:
        t = t[:MAX_INPUT_CHARS]
    low = t.lower()
    for marker in INJECTION_MARKERS:
        while marker in low:
            idx = low.find(marker)
            t = t[:idx] + "[removed]" + t[idx + len(marker):]
            low = t.lower()
    return t.strip()


def validate_output(obj) -> Optional[dict]:
    """Output rail: accept the model's reply only when every field is one
    of the permitted values. Returns a clean dict, or None to reject."""
    if not isinstance(obj, dict):
        return None
    sentiment = str(obj.get("sentiment", "")).lower().strip()
    if sentiment not in SENTIMENT_LABELS:
        return None
    event_type = str(obj.get("event_type", "")).lower().strip()
    if event_type not in EVENT_TYPES:
        event_type = "general"
    severity = str(obj.get("severity", "")).lower().strip()
    if severity not in SEVERITIES:
        severity = "low"
    try:
        score = float(obj.get("sentiment_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(-1.0, min(1.0, score))
    return {
        "sentiment": sentiment,
        "event_type": event_type,
        "severity": severity,
        "sentiment_score": round(score, 2),
    }
