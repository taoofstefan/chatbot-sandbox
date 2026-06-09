"""The agent driver loop.

This is the orchestrator: it doesn't know how to talk to any specific
model, and it doesn't know how to execute any specific tool. It just
runs the loop:

    send messages + tools to backend
    parse response
    if tool calls: execute them, append results, loop
    if <done/>:    record final answer, stop
    else:          prompt the model to commit, loop

The two collaborators are:

  - A `chat` callable (signature: `(messages, tools) -> ChatResponse`).
    We accept a callable, not a Backend, so the driver is trivially
    testable with a MockChatBackend.

  - A `ToolRegistry` and `Sandbox`. The registry is the allowlist; the
    sandbox is the per-run filesystem root.

The driver also produces a `RunState` with the full audit trail —
that's what gets graded and what the LLM-judge inspects.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict

from ..backends.base import ChatResponse
from .sandbox import Sandbox
from .sentinel import parse_assistant_message
from .state import ModelResponse, RunState, ToolCallRecord
from .tools_base import ToolRegistry, ToolResult

# A chat callable. The driver never depends on a concrete Backend type.
ChatFn = Callable[[list[dict[str, object]], list[dict[str, object]] | None], ChatResponse]


SYSTEM_PROMPT_TEMPLATE = """\
You are an AI agent working on a coding/engineering task.

You have access to a set of tools. To call a tool, emit a <tool_call> block:

<tool_call>
{{"name": "<tool_name>", "arguments": {{...}}}}
</tool_call>

When you are finished and ready to give your final answer, emit:

<done/>
<final_answer>
...
</final_answer>

Rules:
- Make one tool call at a time and wait for the result before deciding what to do next.
- If a tool returns an error, read the error and try a different approach. Don't loop forever.
- If you're stuck, say what you tried and what blocked you in <final_answer>.
- Do not invent tools that aren't listed.
- Keep your final answer concise. Reference concrete file paths and line numbers when relevant.
"""


NATIVE_SYSTEM_PROMPT_TEMPLATE = """\
You are an AI agent working on a coding/engineering task.

You have access to a set of tools. Use the platform's native function-calling
interface (e.g. Ollama's `tools` field) to invoke them. To produce a tool
call, return an assistant message whose `tool_calls` field is populated.

To finish, simply return an assistant message with no `tool_calls`. The text
of that message is your final answer.

Rules:
- Make one tool call at a time and wait for the result before deciding what to do next.
- If a tool returns an error, read the error and try a different approach. Don't loop forever.
- If you're stuck, say what you tried and what blocked you.
- Do not invent tools that aren't listed.
- Keep your final answer concise. Reference concrete file paths and line numbers when relevant.
"""


def build_system_prompt(registry: ToolRegistry, *, used_native: bool) -> str:
    """Compose the system prompt with the tool catalog embedded.

    The two modes (native function-calling vs sentinel) have different
    termination semantics, so the prompt differs.
    """
    if used_native:
        return NATIVE_SYSTEM_PROMPT_TEMPLATE + "\n" + registry.system_prompt_block()
    return SYSTEM_PROMPT_TEMPLATE + "\n" + registry.system_prompt_block()


def render_tool_for_native(tool_name: str, registry: ToolRegistry) -> dict[str, object]:
    """Render a tool's schema into the OpenAI/Ollama-native tool-call format."""
    tool = registry.get(tool_name)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.schema),
        },
    }


def to_model_response(
    chat_resp: ChatResponse,
    *,
    used_native: bool,
) -> ModelResponse:
    """Convert a backend's `ChatResponse` into the agent-side `ModelResponse`.

    If we used native function calling, the tool_calls are already
    structured and the final-answer sentinel is irrelevant (the model
    just stops calling tools). If we used sentinel mode, parse the
    content for `<tool_call>` blocks and `<done/>`.
    """
    if used_native:
        return ModelResponse(
            content=chat_resp.content,
            tool_calls=list(chat_resp.tool_calls),
            final_answer=None,  # determined by the driver: empty tools == done
            raw=dict(chat_resp.raw),
        )
    parsed = parse_assistant_message(chat_resp.content)
    return ModelResponse(
        content=chat_resp.content,
        tool_calls=[
            {"name": tc.name, "arguments": tc.arguments}
            for tc in parsed.tool_calls
        ],
        final_answer=parsed.final_answer,
        raw=dict(chat_resp.raw),
    )


def run_agent(
    *,
    user_prompt: str,
    sandbox: Sandbox,
    registry: ToolRegistry,
    chat: ChatFn,
    max_steps: int = 15,
    use_native_tool_calling: bool | None = None,
) -> RunState:
    """Run the agent loop once and return the final RunState.

    Args:
        user_prompt: The task text from `prompts.yaml`.
        sandbox: The per-run filesystem root.
        registry: The tool allowlist for this case.
        chat: Callable that takes (messages, tools) and returns a
            ChatResponse. Typically `backend.chat`.
        max_steps: Hard cap on the number of model calls.
        use_native_tool_calling: True to use the backend's native
            function-calling API, False to use the sentinel format,
            None to auto-detect (native if the backend advertises it).

    Returns:
        A RunState with the full message log, audit trail of tool
        calls, final answer (or None), and a `completed_normally` flag.
    """
    used_native = _resolve_native_flag(chat, use_native_tool_calling)
    tools_for_native: list[dict[str, object]] | None = None
    if used_native:
        tools_for_native = [
            render_tool_for_native(n, registry) for n in registry.names()
        ]

    system_prompt = build_system_prompt(registry, used_native=used_native)
    messages: list[dict[str, object]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    state = RunState(messages=list(messages))

    step = 0
    while step < max_steps:
        step += 1
        state.total_steps = step

        try:
            chat_resp = chat(list(messages), tools_for_native)
        except Exception as e:
            state.error = f"backend chat raised {type(e).__name__}: {e}"
            return state

        model_resp = to_model_response(chat_resp, used_native=used_native)

        # Record the assistant turn in the message log.
        # In native mode, also keep the raw tool_calls so the model
        # sees the same shape on the next turn that it sent.
        assistant_msg: dict[str, object] = {"role": "assistant", "content": model_resp.content}
        if used_native and model_resp.tool_calls:
            assistant_msg["tool_calls"] = _ollama_shape_tool_calls(model_resp.tool_calls)
        messages.append(assistant_msg)
        state.messages = list(messages)

        # If the model made no tool calls, treat that as "done" in native
        # mode (the driver alone decides termination). In sentinel mode
        # the model must emit <done/>.
        if not model_resp.has_tool_calls:
            if used_native:
                state.final_answer = model_resp.content.strip() or ""
                state.completed_normally = True
                return state
            if model_resp.has_final_answer:
                state.final_answer = (model_resp.final_answer or "").strip()
                state.completed_normally = True
                return state
            # Sentinel mode but no <done/>: nudge the model to commit.
            if step < max_steps:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You didn't call a tool and didn't emit <done/>. "
                            "If you are finished, emit <done/><final_answer>...</final_answer>. "
                            "Otherwise, call a tool."
                        ),
                    }
                )
                state.messages = list(messages)
            continue

        # Execute each tool call in order.
        for call in model_resp.tool_calls:
            record = _execute_one_tool(call, sandbox, registry, step)
            state.tool_calls.append(record)
            messages.append(_tool_result_message(record, used_native=used_native))
            state.messages = list(messages)

    # Out of steps.
    state.error = f"max_steps={max_steps} reached without <done/> or final answer"
    return state


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_native_flag(chat: ChatFn, requested: bool | None) -> bool:
    """Decide whether to use native function calling.

    The flag is per-backend. We can't introspect a bare callable, so
    the driver takes the explicit `use_native_tool_calling` from the
    prompt config; `None` means "caller didn't say", and we default to
    False (sentinel mode) for safety. Callers that want auto-detect
    should pass an explicit value.
    """
    if requested is None:
        return False
    return bool(requested)


def _ollama_shape_tool_calls(tool_calls: list[dict[str, object]]) -> list[dict[str, object]]:
    """Re-shape agent-side tool calls into the Ollama-native format.

    Ollama expects `tool_calls[i].function.{name, arguments}` — the
    same shape it sent us on the previous turn. We send it back so the
    model can correlate its own tool calls with the tool results.
    """
    out: list[dict[str, object]] = []
    for i, tc in enumerate(tool_calls):
        raw_args = tc.get("arguments")
        args_dict: dict[str, object] = dict(raw_args) if isinstance(raw_args, dict) else {}
        out.append(
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": tc.get("name"),
                    "arguments": args_dict,
                },
            }
        )
    return out


def _execute_one_tool(
    call: dict[str, object],
    sandbox: Sandbox,
    registry: ToolRegistry,
    step_index: int,
) -> ToolCallRecord:
    """Dispatch one tool call and return the audit record.

    Unknown tools and exceptions are recorded, not raised. The driver
    always gets back a `ToolCallRecord` so the message log can include
    the error for the model to see on the next turn.
    """
    name = call.get("name")
    args = call.get("arguments") or {}
    if not isinstance(name, str) or not name:
        return ToolCallRecord(
            step_index=step_index,
            tool_name="<missing>",
            arguments={},
            ok=False,
            error="tool call missing 'name'",
        )
    if not isinstance(args, dict):
        return ToolCallRecord(
            step_index=step_index,
            tool_name=name,
            arguments={},
            ok=False,
            error=f"tool call 'arguments' must be a dict, got {type(args).__name__}",
        )
    if not registry.has(name):
        return ToolCallRecord(
            step_index=step_index,
            tool_name=name,
            arguments=dict(args),
            ok=False,
            error=(
                f"tool {name!r} is not in the allowlist for this case; "
                f"available: {registry.names()}"
            ),
        )
    tool = registry.get(name)
    t0 = time.perf_counter()
    try:
        result: ToolResult = tool.execute(dict(args), sandbox)
    except Exception as e:
        return ToolCallRecord(
            step_index=step_index,
            tool_name=name,
            arguments=dict(args),
            ok=False,
            error=f"tool raised {type(e).__name__}: {e}",
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    return ToolCallRecord(
        step_index=step_index,
        tool_name=name,
        arguments=dict(args),
        ok=result.ok,
        output=dict(result.output),
        error=result.error,
        duration_ms=result.duration_ms or int((time.perf_counter() - t0) * 1000),
    )


def _tool_result_message(record: ToolCallRecord, *, used_native: bool) -> dict[str, object]:
    """Build the chat message that feeds the tool result back to the model.

    Native mode (Ollama): `{"role": "tool", "content": ...}` — but Ollama
    also wants to know which tool call this is the result of. We
    synthesize a `tool_call_id` matching the shape we used in
    `_ollama_shape_tool_calls`. The exact field Ollama uses for
    matching isn't fully documented; we set both `name` and a
    synthetic `id` to maximize compatibility.
    """
    payload: dict[str, object] = {
        "ok": record.ok,
        "output": record.output,
    }
    if record.error is not None:
        payload["error"] = record.error
    content = json.dumps(payload, default=str)
    if used_native:
        # Ollama accepts "tool" role; we tag the call so the model can
        # correlate. Use the same id scheme as _ollama_shape_tool_calls.
        return {
            "role": "tool",
            "name": record.tool_name,
            "content": content,
        }
    return {"role": "user", "content": f"Tool result for {record.tool_name}:\n{content}"}


def run_state_to_dict(state: RunState) -> dict[str, object]:
    """Serialize a RunState for storage or display."""
    return {
        "messages": list(state.messages),
        "tool_calls": [
            {
                "step_index": tc.step_index,
                "tool_name": tc.tool_name,
                "arguments": dict(tc.arguments),
                "ok": tc.ok,
                "output": dict(tc.output),
                "error": tc.error,
                "duration_ms": tc.duration_ms,
            }
            for tc in state.tool_calls
        ],
        "final_answer": state.final_answer,
        "completed_normally": state.completed_normally,
        "total_steps": state.total_steps,
        "error": state.error,
    }


def grade_run(
    state: RunState,
    validators: dict[str, object],
    sandbox: Sandbox | None = None,
) -> dict[str, dict[str, object]]:
    """Run the agent graders over `state` and attach the report.

    This is a small convenience that imports the graders lazily and
    returns the same shape `grade()` returns in `chatbot_sandbox.graders`:
    `{check_name: {"passed": bool, "detail": str}}`.
    """
    from .graders import grade_agent

    return grade_agent(state, validators, sandbox=sandbox)


__all__ = [
    "ChatFn",
    "ModelResponse",
    "RunState",
    "ToolCallRecord",
    "build_system_prompt",
    "grade_run",
    "render_tool_for_native",
    "run_agent",
    "run_state_to_dict",
    "to_model_response",
]


# Silence unused-import warning for asdict (kept for future use).
_ = asdict
