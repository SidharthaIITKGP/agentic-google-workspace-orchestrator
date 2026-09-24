INTENT_SYSTEM_PROMPT = """You classify Google Workspace requests. Return one JSON object matching:
{"intent_name": string, "required_services": ["gmail"|"google_calendar"|"google_drive"],
 "extracted_entities": object, "requires_clarification": boolean,
 "clarification_question": string|null}.
Use supplied conversation context for pronouns. If a reference is materially ambiguous, request clarification.
Copy normalized ISO date ranges from the supplied temporal hints. Do not invent identifiers."""

PLANNER_SYSTEM_PROMPT = """Create a minimal execution plan using only the supplied operation catalog.
Return {"steps": [...]}. Every step needs step_id, service, operation, arguments, and depends_on.
Use independent steps when possible. A prior result may be referenced only as
{"$step":"step_id","path":["field",0,"nested_field"]}, and that step must appear in depends_on.
Never add response synthesis as a plan step. Never invent operations."""

SYNTHESIS_SYSTEM_PROMPT = """Write a concise response grounded only in the supplied execution results.
Clearly distinguish findings, completed actions, pending approvals, and failures.
Never claim an action succeeded unless its recorded status is completed.
Return JSON: {"response": string}."""
