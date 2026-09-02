from typing import TypedDict

from langgraph.graph import StateGraph

from coach_agent.agent import call_agent


class GraphState(TypedDict):
    messages: list[dict]
    system_prompt: str
    response: str


def _call_llm(state: GraphState) -> GraphState:
    response = call_agent(state["messages"], state["system_prompt"])
    return {"response": response}


_graph_builder = StateGraph(GraphState)
_graph_builder.add_node("call_llm", _call_llm)
_graph_builder.set_entry_point("call_llm")
_graph_builder.set_finish_point("call_llm")
graph = _graph_builder.compile()


def run_graph(messages: list[dict], system_prompt: str) -> str:
    result = graph.invoke({"messages": messages, "system_prompt": system_prompt, "response": ""})
    return result["response"]
