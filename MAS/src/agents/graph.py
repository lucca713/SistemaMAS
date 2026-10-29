"""
Grafo do modulo de raciocinio (linha src/agents/*).

Fica separado de src/core/graph.py, que compila a outra implementacao do
projeto (src/core/nodes.py). As duas convivem sobre o mesmo src/core/state.py.

Topologia (malha fechada):

        SUPERVISOR <-------------+
         |   |    |              |
         v   v    v              |
    PLANNER EXECUTOR END         |
         |   |                   |
         +---+-------------------+

A instrumentacao de metricas e feita por wrapper nos nos, para manter os
arquivos dos agentes livres de codigo de medicao.
"""

import time

from langgraph.graph import END, StateGraph

from src.agents._metrics import get_metrics
from src.agents.executor import execute_node
from src.agents.planner import plan_node
from src.agents.supervisor import supervise_node
from src.core.state import (
    MISSION_REPLANNING,
    NODE_EXECUTOR,
    NODE_PLANNER,
    NODE_SUPERVISOR,
    AgentState,
)


def router(state: AgentState):
    """Le a decisao registrada pelo Supervisor em `next_node`."""
    destino = state.get("next_node")
    if destino == "END":
        return END
    if destino in (NODE_PLANNER, NODE_EXECUTOR, NODE_SUPERVISOR):
        return destino
    print(f"[Graph] Rota desconhecida '{destino}'; encerrando por seguranca.")
    return END


def _instrumentado(nome, fn):
    """Mede a latencia do no e alimenta a MissionMetrics, se houver uma ativa."""
    def wrapper(state):
        t0 = time.time()
        saida = fn(state) or {}
        m = get_metrics()
        if m is not None:
            dt = time.time() - t0
            m.record_decision(nome, dt)
            if nome == NODE_PLANNER:
                m.record_plan_latency(dt)   # PL
            if saida.get("mission_status") == MISSION_REPLANNING:
                m.record_replan()
            if (saida.get("last_ros_feedback") or {}).get("tool"):
                m.record_tool_call()
        return saida
    wrapper.__name__ = f"{nome}_node"
    return wrapper


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node(NODE_SUPERVISOR, _instrumentado(NODE_SUPERVISOR, supervise_node))
    workflow.add_node(NODE_PLANNER, _instrumentado(NODE_PLANNER, plan_node))
    workflow.add_node(NODE_EXECUTOR, _instrumentado(NODE_EXECUTOR, execute_node))

    workflow.set_entry_point(NODE_SUPERVISOR)

    workflow.add_conditional_edges(
        NODE_SUPERVISOR,
        router,
        {
            NODE_PLANNER: NODE_PLANNER,
            NODE_EXECUTOR: NODE_EXECUTOR,
            NODE_SUPERVISOR: NODE_SUPERVISOR,  # polling do closed-loop
            END: END,
        },
    )

    workflow.add_edge(NODE_PLANNER, NODE_SUPERVISOR)
    workflow.add_edge(NODE_EXECUTOR, NODE_SUPERVISOR)

    return workflow.compile()
