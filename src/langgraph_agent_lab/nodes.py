"""Node functions for the LangGraph workflow.

Each function receives AgentState and returns a partial state update dict.
Do NOT mutate input state — return new values only.

LLM REQUIREMENT:
- classify_node MUST use a real LLM call (structured output for intent classification)
- answer_node MUST use a real LLM call (grounded response generation)
- evaluate_node SHOULD use LLM-as-judge (bonus points; heuristic acceptable for base score)
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from .llm import get_llm
from .state import AgentState, make_event


class Classification(BaseModel):
    """Structured result required from the intent-classification model."""

    route: Literal["simple", "tool", "missing_info", "risky", "error"]
    risk_level: Literal["low", "high"] = "low"


def _field_value(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(field, default)
    return getattr(value, field, default)


def _response_text(response: Any) -> str:
    """Extract text from a normal response or LangChain block content."""
    content = (
        response.get("content", response)
        if isinstance(response, Mapping)
        else getattr(response, "content", response)
    )
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            text = _field_value(block, "text")
            if text is not None:
                parts.append(str(text))
        return "".join(parts)
    return "" if content is None else str(content)


def _classification_prompt(query: str) -> str:
    return f"""Classify this support request into exactly one route:
- simple: a general question, explanation, or step-by-step instruction that can be answered
  from general knowledge without retrieving a current record or taking an external action
- tool: explicitly asks to look up, search, retrieve, track, or inspect current information
- missing_info: too vague to act on safely because an essential detail or requested outcome is
  absent
- risky: requests an external, destructive, financial, or otherwise sensitive action
- error: reports a transient or unrecoverable system or processing failure

When more than one category seems possible, use this priority:
risky > tool > missing_info > error > simple.
Important distinctions:
- Instructions or explanations must never be tool merely because they mention an account,
  password, order, or other object. They are simple when no current record is requested.
- A tool route requires a request for a current record or lookup, not merely a question about
  how something works.
- Use missing_info for vague requests such as "fix it" when the target or desired outcome is
  not stated. Use error only when the request describes a system failure.

Return only the route and a risk level of low or high. Do not infer facts that are not in the
request.

Support request:
{query}
"""


# ─── EXAMPLE: working node (provided for reference) ──────────────────
def intake_node(state: AgentState) -> dict:
    """Normalize raw query. This node is provided as a working example."""
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [make_event("intake", "completed", "query normalized")],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using an LLM.

    *** MUST use a real LLM call — keyword-only heuristics will lose points. ***

    Use .with_structured_output() or equivalent to get reliable enum classification.
    The LLM should classify into one of: simple, tool, missing_info, risky, error.

    Hints:
    - See llm.py for the get_llm() helper
    - Use Pydantic model or TypedDict with .with_structured_output()
    - Set risk_level to "high" for risky routes, "low" otherwise
    - Priority guide: risky > tool > missing_info > error > simple

    Return: {"route": str, "risk_level": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")
    response = get_llm().with_structured_output(Classification).invoke(
        _classification_prompt(query)
    )
    route = _field_value(response, "route", "error")
    try:
        classification = Classification(
            route=route,
            risk_level=_field_value(response, "risk_level", "low"),
        )
    except Exception:
        classification = Classification(route="error", risk_level="low")

    risk_level = "high" if classification.route == "risky" else "low"
    return {
        "route": classification.route,
        "risk_level": risk_level,
        "events": [
            make_event(
                "classify",
                "completed",
                f"request classified as {classification.route}",
                route=classification.route,
                risk_level=risk_level,
            )
        ],
    }


def tool_node(state: AgentState) -> dict:
    """Execute a mock tool call.

    Simulate transient failures for error-route scenarios to test retry loops.

    Requirements:
    - Read current attempt count from state
    - If route is "error" and attempt < 2: return error result (string containing "ERROR")
    - Otherwise: return a mock success result string
    - Append result to tool_results list

    Return: {"tool_results": [result_string], "events": [make_event(...)]}
    """
    attempt = int(state.get("attempt", 0) or 0)
    query = state.get("query", "")
    if state.get("route") == "error" and attempt < 2:
        result = f"ERROR: transient mock tool failure on attempt {attempt + 1}"
        event_type = "error"
    else:
        result = f"mock tool result for request: {query}"
        event_type = "completed"
    return {
        "tool_results": [result],
        "events": [make_event("tool", event_type, result, attempt=attempt)],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the retry-loop gate.

    Check whether the latest tool result is satisfactory or needs retry.

    SHOULD use LLM-as-judge for bonus points. Heuristic (e.g., check for "ERROR" substring)
    is acceptable for base score.

    Requirements:
    - Read the latest entry from tool_results
    - Set evaluation_result to "needs_retry" or "success"
    - This field drives route_after_evaluate conditional edge

    Note: You may need to add 'evaluation_result' to AgentState if not present.

    Return: {"evaluation_result": str, "events": [make_event(...)]}
    """
    results = state.get("tool_results", []) or []
    latest = str(results[-1]) if results else ""
    evaluation_result = "needs_retry" if "ERROR" in latest.upper() else "success"
    return {
        "evaluation_result": evaluation_result,
        "events": [
            make_event(
                "evaluate",
                "completed",
                f"tool result evaluated as {evaluation_result}",
                evaluation_result=evaluation_result,
            )
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Generate a final response using an LLM.

    *** MUST use a real LLM call — hardcoded strings will lose points. ***

    The LLM should generate a helpful response grounded in available context:
    - tool_results (if any)
    - approval decision (if risky route)
    - original query

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    context = {
        "query": state.get("query", ""),
        "tool_results": state.get("tool_results", []) or [],
        "proposed_action": state.get("proposed_action"),
        "approval": state.get("approval"),
    }
    prompt = (
        "Answer the user's request helpfully and concisely. Ground the answer only in the "
        "request and the available context below; do not invent tool results or claim an "
        "action was completed unless the context supports it.\n\n"
        f"Current context:\n{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
    )
    response = get_llm().invoke(prompt)
    final_answer = _response_text(response).strip()
    return {
        "final_answer": final_answer,
        "events": [make_event("answer", "completed", "answer generated")],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    Generate a specific clarification question based on the vague/incomplete query.

    Note: You may need to add 'pending_question' to AgentState if not present.

    Return: {"pending_question": str, "final_answer": str, "events": [make_event(...)]}
    """
    query = state.get("query", "").strip()
    if query:
        question = f"Could you clarify what outcome you want for this request: {query}"
    else:
        question = "Could you provide more details about the request and the outcome you want?"
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "clarification requested")],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for human approval.

    Describe the proposed action and why it requires approval.

    Note: You may need to add 'proposed_action' to AgentState if not present.

    Return: {"proposed_action": str, "events": [make_event(...)]}
    """
    query = state.get("query", "").strip()
    proposed_action = f"Proposed action: {query}. Approval is required before execution."
    return {
        "proposed_action": proposed_action,
        "events": [make_event("risky_action", "completed", "risky action prepared")],
    }


def approval_node(state: AgentState) -> dict:
    """Human-in-the-loop approval step.

    Default behavior: mock approval (approved=True) so tests and CI run offline.
    Extension: if env LANGGRAPH_INTERRUPT=true, use langgraph.types.interrupt() for real HITL.

    Return: {"approval": {"approved": bool, "reviewer": str, "comment": str},
    "events": [make_event(...)]}
    """
    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        decision = interrupt(
            {
                "proposed_action": state.get("proposed_action", ""),
                "query": state.get("query", ""),
            }
        )
        if isinstance(decision, Mapping):
            approval = {
                "approved": bool(decision.get("approved", False)),
                "reviewer": str(decision.get("reviewer", "human-reviewer")),
                "comment": str(decision.get("comment", "")),
            }
        else:
            approval = {
                "approved": bool(decision),
                "reviewer": "human-reviewer",
                "comment": "",
            }
    else:
        approval = {
            "approved": True,
            "reviewer": "mock-reviewer",
            "comment": "mock approval",
        }
    return {
        "approval": approval,
        "events": [
            make_event(
                "approval",
                "completed",
                "approval decision recorded",
                approved=approval["approved"],
                reviewer=approval["reviewer"],
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt.

    Increment the attempt counter and log the transient failure.

    Requirements:
    - Read current attempt from state, increment by 1
    - Add an error message to errors list
    - Return updated attempt count

    Return: {"attempt": int, "errors": [str], "events": [make_event(...)]}
    """
    attempt = int(state.get("attempt", 0) or 0) + 1
    error_message = f"retry attempt {attempt}: transient tool failure"
    return {
        "attempt": attempt,
        "errors": [error_message],
        "events": [make_event("retry", "completed", error_message, attempt=attempt)],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Handle unresolvable failures after max retries exceeded.

    This is the third layer: retry → fallback → dead letter.
    Log the failure and set a final_answer explaining that the request could not be completed.

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    attempt = int(state.get("attempt", 0) or 0)
    message = f"The request could not be completed after {attempt} attempt(s)."
    return {
        "final_answer": message,
        "events": [make_event("dead_letter", "completed", message, attempt=attempt)],
    }


def finalize_node(state: AgentState) -> dict:
    """Emit a final audit event. All routes must pass through here before END.

    Return: {"events": [make_event("finalize", "completed", "workflow finished")]}
    """
    return {"events": [make_event("finalize", "completed", "workflow finished")]}
