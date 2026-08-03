"""Layer 3 -- the nine logical agents as typed graph nodes.

Only four are LLM-backed (ADR-0003); the rest are deterministic. Imports no `db`
(boundary R5) -- agents are pure functions of workflow state.
"""
