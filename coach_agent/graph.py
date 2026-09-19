import base64
import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from coach_agent.agent import call_agent, extract_text
from coach_agent.reports import Document
from coach_agent.tools import (
    COACH_TOOLS,
    ToolContext,
    describe_call,
    needs_confirmation,
    run_tool,
)


@dataclass(frozen=True)
class ImageAttachment:
    """One image on its way to the model, as the channel layer holds it.

    Telegram hands over bytes and a type and knows nothing else; the base64 the
    API wants is an encoding detail of *this* layer, so it happens here.
    """

    data: bytes
    media_type: str


@dataclass(frozen=True)
class UserInput:
    """What the user sent this turn, before it is anything Anthropic-shaped.

    The channel layer builds this and stops. Which blocks it becomes is decided
    below and nowhere else — so a second channel (Phase 7) has to know how to
    pull a photo out of its own updates, and that is all it has to know.
    """

    text: str
    image: ImageAttachment | None = None


# Stands in the conversation history for an image that was sent once. What the
# model saw is carried from here on by its own reply, which is text and costs
# text; the image itself is not kept, because a checkpointed image block is
# re-sent, and re-billed, on every later turn of the same conversation.
_IMAGE_PLACEHOLDER = "[תמונה שהמשתמש שלח]"


def _image_block(image: ImageAttachment) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": image.media_type,
            "data": base64.standard_b64encode(image.data).decode(),
        },
    }


def _opening_text(user_input: UserInput) -> str:
    """The text that enters the history for this turn.

    A photo usually arrives with a caption ("זה מה שאכלתי") but not always, and
    a message with empty content is rejected by the API — so the placeholder is
    also what keeps a caption-less photo a legal turn.
    """
    if user_input.image is None:
        return user_input.text
    return f"{_IMAGE_PLACEHOLDER} {user_input.text}".strip()


class GraphState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    system_prompt: str
    # The mode lives here and nowhere else: intake and coaching are the same
    # three nodes running with a different prompt and a different tool set, so
    # putting both in state means no second graph and no flag to keep in sync.
    tools: list[dict]
    user_key: str
    response: str
    # This turn's image, already in API shape, held apart from `messages` so it
    # is never checkpointed into the history. Each turn overwrites it, so a
    # later text-only message clears the previous photo rather than inheriting
    # it — `messages` is append-only, this is not.
    image_block: dict | None


_EMPTY_RESPONSE_FALLBACK = "לא הצלחתי לנסח תשובה הפעם. אפשר לנסות שוב?"


def _with_image(messages: list[dict], image_block: dict | None) -> list[dict]:
    """The messages as the API should see them on this call, image included.

    The picture is attached to the message that opened the turn, and only while
    that message is still the last one — so a tool round-trip inside the same
    turn does not buy it a second time. A turn-opening message carries a plain
    string; a tool result carries a list of blocks, which is what tells the two
    apart. `messages` itself is never touched: what the checkpointer keeps, and
    what every later turn is billed for, stays the placeholder text.
    """
    if image_block is None:
        return messages
    opening = messages[-1]
    if opening["role"] != "user" or not isinstance(opening["content"], str):
        return messages
    # Image before text: the caption ("זה מה שאכלתי") is a question about the
    # picture, and the model answers it better having already seen it.
    return messages[:-1] + [
        {
            "role": "user",
            "content": [image_block, {"type": "text", "text": opening["content"]}],
        }
    ]


def _call_llm(state: GraphState) -> GraphState:
    messages = _with_image(state["messages"], state["image_block"])
    message = call_agent(messages, state["system_prompt"], tools=state["tools"])
    content = [block.model_dump() for block in message.content]
    update: GraphState = {"messages": [{"role": "assistant", "content": content}]}
    # Same signal the router uses. Deciding this from stop_reason instead let the
    # two disagree — a turn truncated mid tool_use has no text to extract, and the
    # old code raised before the router ever got to send it to the tool.
    if not any(block["type"] == "tool_use" for block in content):
        update["response"] = extract_text(message) or _EMPTY_RESPONSE_FALLBACK
    return update


_APPROVE = "approve"

# What the model is told when a write it proposed did not happen. It reads the
# outcome as a tool result like any other, so the alternative — silence, or a
# result that says "נרשם" — is a coach that reports a row nobody stored.
_REJECTED_RESULT = (
    "המתאמן לא אישר את הרישום, ולא נשמר כלום. "
    "לא לנסות לרשום את אותו הדבר שוב — לשאול מה לתקן, או להמשיך בשיחה."
)
_REPLIED_RESULT = (
    'המתאמן לא אישר את הרישום. במקום ללחוץ על כפתור הוא כתב: "{text}". '
    "לא נשמר כלום. אם זה תיקון — להציע את הרישום מחדש עם הערכים המתוקנים."
)


def _assistant_text(message: dict) -> str:
    """What the model said in the turn it also asked to write something.

    Until now this was dropped on the floor: a turn holding a tool_use never
    reaches the user, so its text blocks went nowhere. It is the one sentence
    that explains the numbers underneath it, so the approval carries it.
    """
    return "\n".join(
        block["text"] for block in message["content"] if block.get("type") == "text"
    ).strip()


def _refusal(decision: dict) -> str:
    if decision.get("action") == "reply":
        return _REPLIED_RESULT.format(text=decision.get("text", ""))
    return _REJECTED_RESULT


def _run_tool(state: GraphState, config: RunnableConfig) -> GraphState:
    # The annotation is load-bearing, not decoration: LangGraph decides whether
    # to hand a node the config by reading this type, and a plain `dict` gets a
    # warning at build time and a TypeError at run time.
    last_message = state["messages"][-1]
    calls = [block for block in last_message["content"] if block.get("type") == "tool_use"]
    gated = [block for block in calls if needs_confirmation(block["name"])]

    # Asked before a single handler runs, and not only before the gated ones:
    # `interrupt` resumes by replaying this node from its first line, so a tool
    # that ran above it would run a second time on the way back.
    decision = (
        interrupt(
            {
                "text": _assistant_text(last_message),
                "rows": [describe_call(b["name"], b.get("input") or {}) for b in gated],
            }
        )
        if gated
        else {"action": _APPROVE}
    )

    gated_ids = {block["id"] for block in gated}
    approved = decision.get("action") == _APPROVE
    context = ToolContext(user_key=state["user_key"], outbox=config["configurable"]["outbox"])
    tool_results = []
    for block in calls:
        if block["id"] in gated_ids and not approved:
            content = _refusal(decision)
        else:
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


@dataclass(frozen=True)
class AgentReply:
    """One answer on its way back to the channel layer.

    A turn now ends in one of two ways — an answer, or a question the graph is
    parked on — and the difference decides whether the message carries buttons.
    Said in the return value rather than left for the channel to infer from the
    text, which would be guessing at Hebrew.

    `documents` is the outbound mirror of `UserInput.image`: files a tool built
    for the person, carried out in the same shape they came in — bytes, a type
    and a name — so the channel layer stays the only thing that knows how its
    own platform sends a file.
    """

    text: str
    awaiting_approval: bool = False
    documents: tuple[Document, ...] = ()


def _config(thread_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            # What the tools made for the person rather than for the model.
            #
            # It rides on the config and not in GraphState because state is
            # checkpointed: as an append-only channel every rendered page would
            # be kept for the life of the thread, growing ~10KB per report and
            # re-delivered on every later turn, and as an overwritten one a
            # second report in the same turn would erase the first. The config
            # is built per call below and thrown away with it, which is exactly
            # the lifetime a file being sent once should have.
            #
            # ⚠️ This holds because MemorySaver never serialises the config. If
            # the checkpointer is ever swapped for SqliteSaver (open question in
            # מסמך TODO.md), check that assumption before trusting this.
            "outbox": [],
        },
        # LangSmith groups traces into a thread by this metadata key, which is what
        # turns per-message cost into per-conversation cost. It is the user key, so a
        # thread is that user's whole history — nothing marks a conversation as over.
        "metadata": {"thread_id": thread_id},
    }


def _pending(config: dict) -> dict | None:
    """The approval this thread is parked on, if it is parked on one.

    `get_state` on a thread that has never run returns an empty snapshot rather
    than raising, so this answers for a first-ever message too.
    """
    interrupts = graph.get_state(config).interrupts
    return interrupts[0].value if interrupts else None


def _approval_text(value: dict) -> str:
    """The model's sentence, then the rows it is asking to write underneath it."""
    return "\n\n".join(part for part in (value["text"], "\n".join(value["rows"])) if part)


def _invoke(config: dict, payload: dict | Command) -> AgentReply:
    result = graph.invoke(payload, config=config)
    # Whatever the tools left behind this run. Read on both paths and not only
    # the answering one: a turn that ends parked has produced nothing yet today,
    # but a report tool added beside a gated write must not depend on that.
    documents = tuple(config["configurable"]["outbox"])
    # Asked of the checkpointer and not of `result`: the key an interrupted run
    # adds to its return value was made private in LangGraph 1.0, while the
    # snapshot is the supported way to ask the same question.
    pending = _pending(config)
    if pending is not None:
        return AgentReply(_approval_text(pending), awaiting_approval=True, documents=documents)
    return AgentReply(result["response"], documents=documents)


def run_graph(
    user_key: str,
    user_message: str | UserInput,
    system_prompt: str,
    tools: list[dict] | None = None,
    thread_id: str | None = None,
) -> AgentReply:
    """Run one turn for the user identified by `user_key`.

    The key arrives already built by the channel layer, so nothing here knows
    which channel the message came from — only that this string isolates one
    user's history from another's.
    """
    # The intake runs on its own thread, so the coach does not carry twenty
    # minutes of interview in every later message: the two documents *are* the
    # summary of that conversation, which is the whole reason they were written.
    # A plain string still means a plain text turn, so the text and voice paths
    # read exactly as they did — voice reduces to text before it ever gets here.
    user_input = user_message if isinstance(user_message, UserInput) else UserInput(user_message)

    config = _config(thread_id or user_key)
    if _pending(config) is not None:
        # A message typed while an approval is open is not a new turn. The graph
        # is parked mid-node holding a row it has not written, and whatever was
        # just typed is about that row — "בלי הלחם" has to reach the model as an
        # answer to the question it asked, not as a fresh remark it never linked
        # to it. It is not an approval either: those arrive as a button.
        return _invoke(config, Command(resume={"action": "reply", "text": user_input.text}))

    return _invoke(
        config,
        {
            "messages": [{"role": "user", "content": _opening_text(user_input)}],
            "system_prompt": system_prompt,
            "tools": COACH_TOOLS if tools is None else tools,
            "user_key": user_key,
            "response": "",
            "image_block": _image_block(user_input.image) if user_input.image else None,
        },
    )


def resume_graph(user_key: str, approved: bool, thread_id: str | None = None) -> AgentReply | None:
    """Answer the open approval on this thread, or None if there is none left.

    None is the ordinary case of a button pressed twice, or of one pressed after
    the conversation moved on — the first press consumed the interrupt, and
    resuming a thread that is not parked would start it over.
    """
    config = _config(thread_id or user_key)
    if _pending(config) is None:
        return None
    return _invoke(config, Command(resume={"action": _APPROVE if approved else "reject"}))
