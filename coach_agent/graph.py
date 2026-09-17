import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from coach_agent.agent import call_agent, extract_text
from coach_agent.tools import COACH_TOOLS, ToolContext, run_tool


class GraphState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    system_prompt: str
    # The mode lives here and nowhere else: intake and coaching are the same
    # three nodes running with a different prompt and a different tool set, so
    # putting both in state means no second graph and no flag to keep in sync.
    tools: list[dict]
    user_key: str
    response: str


_EMPTY_RESPONSE_FALLBACK = "לא הצלחתי לנסח תשובה הפעם. אפשר לנסות שוב?"


def _call_llm(state: GraphState) -> GraphState:
    message = call_agent(state["messages"], state["system_prompt"], tools=state["tools"])
    content = [block.model_dump() for block in message.content]
    update: GraphState = {"messages": [{"role": "assistant", "content": content}]}
    # Same signal the router uses. Deciding this from stop_reason instead let the
    # two disagree — a turn truncated mid tool_use has no text to extract, and the
    # old code raised before the router ever got to send it to the tool.
    if not any(block["type"] == "tool_use" for block in content):
        update["response"] = extract_text(message) or _EMPTY_RESPONSE_FALLBACK
    return update


def _run_tool(state: GraphState) -> GraphState:
    last_message = state["messages"][-1]
    context = ToolContext(user_key=state["user_key"])
    tool_results = []
    for block in last_message["content"]:
        if block.get("type") != "tool_use":
            continue
        content = run_tool(block["name"], block.get("input") or {}, context)
        tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content})
    return {"messages": [{"role": "user", "content": tool_results}]}


def _route_after_llm(state: GraphState) -> str:
    last_message = state["messages"][-1]
    if last_message["role"] == "assistant":
        for block in last_message["content"]:
            if block.get("type") == "tool_use":
                return "run_tool"
    return END


_graph_builder = StateGraph(GraphState)
_graph_builder.add_node("call_llm", _call_llm)
_graph_builder.add_node("run_tool", _run_tool)
_graph_builder.set_entry_point("call_llm")
_graph_builder.add_conditional_edges("call_llm", _route_after_llm, {"run_tool": "run_tool", END: END})
_graph_builder.add_edge("run_tool", "call_llm")
graph = _graph_builder.compile(checkpointer=MemorySaver())


def run_graph(
    user_key: str,
    user_message: str,
    system_prompt: str,
    tools: list[dict] | None = None,
    thread_id: str | None = None,
) -> str:
    """Run one turn for the user identified by `user_key`.

    The key arrives already built by the channel layer, so nothing here knows
    which channel the message came from — only that this string isolates one
    user's history from another's.
    """
    # The intake runs on its own thread, so the coach does not carry twenty
    # minutes of interview in every later message: the two documents *are* the
    # summary of that conversation, which is the whole reason they were written.
    thread_id = thread_id or user_key
    config = {
        "configurable": {"thread_id": thread_id},
        # LangSmith groups traces into a thread by this metadata key, which is what
        # turns per-message cost into per-conversation cost. It is the user key, so a
        # thread is that user's whole history — nothing marks a conversation as over.
        "metadata": {"thread_id": thread_id},
    }
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": user_message}],
            "system_prompt": system_prompt,
            "tools": COACH_TOOLS if tools is None else tools,
            "user_key": user_key,
            "response": "",
        },
        config=config,
    )
    return result["response"]
