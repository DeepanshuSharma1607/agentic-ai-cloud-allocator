"""
graph.py - connects the nodes into the LangGraph. No logic of its own, only wiring.

    START -> store_prediction -> trigger_check -> script_creator -+-> llm_unusual -+
                                                                  +-> llm_timer   -+-> apply_and_log -+-> alert_human -> END
                                                                  +-> auto_scale  -+                  +-> END (nothing wrong)

The only two decisions in the graph are the two "route" functions below:
  route_mode  : which of the three branches runs (trigger_check already chose the mode, priority unusual > timer > auto)
  route_alert : alert_human runs only if apply_and_log found a problem
"""
from langgraph.graph import END, START, StateGraph

from agent import config as cfg
from agent import nodes
from agent.state import AgentState


def route_mode(state):
    """Read the mode chosen by trigger_check and return the name of the branch node."""
    return {
        cfg.MODE_UNUSUAL: "llm_unusual",
        cfg.MODE_TIMER: "llm_timer",
        cfg.MODE_AUTO: "auto_scale",
    }[state["mode"]]


def route_alert(state):
    """Go to alert_human only if something is wrong. Otherwise the minute is finished."""
    return "alert_human" if state.get("alert_reason") else END


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("store_prediction", nodes.store_prediction)
    g.add_node("trigger_check", nodes.trigger_check)
    g.add_node("script_creator", nodes.script_creator)
    g.add_node("llm_unusual", nodes.llm_unusual)
    g.add_node("llm_timer", nodes.llm_timer)
    g.add_node("auto_scale", nodes.auto_scale)
    g.add_node("apply_and_log", nodes.apply_and_log)
    g.add_node("alert_human", nodes.alert_human)

    g.add_edge(START, "store_prediction")
    g.add_edge("store_prediction", "trigger_check")
    g.add_edge("trigger_check", "script_creator")
    g.add_conditional_edges("script_creator", route_mode,
                            ["llm_unusual", "llm_timer", "auto_scale"])
    g.add_edge("llm_unusual", "apply_and_log")
    g.add_edge("llm_timer", "apply_and_log")
    g.add_edge("auto_scale", "apply_and_log")
    g.add_conditional_edges("apply_and_log", route_alert, ["alert_human", END])
    g.add_edge("alert_human", END)

    return g.compile()