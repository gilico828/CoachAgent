import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from coach_agent.agent import call_agent


class GraphState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    system_prompt: str
    response: str


def _call_llm(state: GraphState) -> GraphState:
    response = call_agent(state["messages"], state["system_prompt"])
    return {"messages": [{"role": "assistant", "content": response}], "response": response}


_graph_builder = StateGraph(GraphState)
_graph_builder.add_node("call_llm", _call_llm)
_graph_builder.set_entry_point("call_llm")
_graph_builder.set_finish_point("call_llm")
graph = _graph_builder.compile(checkpointer=MemorySaver())


def run_graph(user_id: int, user_message: str, system_prompt: str) -> str:
    config = {"configurable": {"thread_id": str(user_id)}}
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": user_message}],
            "system_prompt": system_prompt,
            "response": "",
        },
        config=config,
    )
    return result["response"]
