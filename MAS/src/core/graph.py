"""
Compilação do StateGraph do Sistema Multi-Agente.

Topologia (malha fechada):

        ┌──────────────┐
        │  SUPERVISOR  │◄─────────────┐
        └──────┬───────┘              │
     ┌─────────┼─────────┬────────────┤
     ▼         ▼         ▼            │
  PLANNER   EXECUTOR    END           │
     │         │                      │
     └─────────┴──────────────────────┘

Arestas condicionais a partir do Supervisor:
  * -> executor  : há subtarefa pendente e navigation_status em (IDLE, SUCCESS);
  * -> planner   : navigation_status em (PATH_BLOCKED, ERROR), ou não há plano ainda;
  * -> supervisor: subtarefa ainda em andamento (polling do ROS 2);
  * -> END       : plano vazio e missão concluída/abortada.
"""

import os
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from src.core.nodes import executor_node, planner_node, supervisor_node
from src.core.state import (
    MISSION_FAILED,
    MISSION_SUCCESS,
    NODE_END,
    NODE_EXECUTOR,
    NODE_PLANNER,
    NODE_SUPERVISOR,
    AgentState,
    MissionMetrics,
    create_initial_state,
)

# Teto de passos do grafo: evita loop recursivo infinito sob falhas repetidas.
GRAPH_RECURSION_LIMIT = int(os.environ.get("MAS_RECURSION_LIMIT", "60"))


def route_from_supervisor(state: AgentState) -> str:
    """Aresta condicional: lê a decisão registrada pelo Supervisor em `next_node`."""
    next_node = state.get("next_node") or NODE_END
    if next_node == NODE_END:
        return END
    if next_node in (NODE_PLANNER, NODE_EXECUTOR, NODE_SUPERVISOR):
        return next_node
    print(f"[Graph] Rota desconhecida '{next_node}'; encerrando por segurança.")
    return END


def build_graph(checkpointer: Optional[Any] = None):
    """Constrói e compila o grafo cognitivo dos três agentes."""
    workflow = StateGraph(AgentState)

    workflow.add_node(NODE_SUPERVISOR, supervisor_node)
    workflow.add_node(NODE_PLANNER, planner_node)
    workflow.add_node(NODE_EXECUTOR, executor_node)

    # O Supervisor é sempre o ponto de entrada da missão.
    workflow.set_entry_point(NODE_SUPERVISOR)

    workflow.add_conditional_edges(
        NODE_SUPERVISOR,
        route_from_supervisor,
        {
            NODE_PLANNER: NODE_PLANNER,
            NODE_EXECUTOR: NODE_EXECUTOR,
            NODE_SUPERVISOR: NODE_SUPERVISOR,  # polling do ROS 2 (closed-loop)
            END: END,
        },
    )

    # Planejador e Executor devolvem sempre o controle ao Supervisor.
    workflow.add_edge(NODE_PLANNER, NODE_SUPERVISOR)
    workflow.add_edge(NODE_EXECUTOR, NODE_SUPERVISOR)

    return workflow.compile(checkpointer=checkpointer)


def run_mission(
    user_instruction: str,
    metrics: Optional[MissionMetrics] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Executa uma missão completa de ponta a ponta e devolve o estado final.

    Registra as métricas de avaliação (taxa de sucesso, latência de decisão e
    resiliência a falhas) no coletor informado.
    """
    from src.core.nodes import set_metrics

    metrics = metrics or MissionMetrics(user_instruction)
    set_metrics(metrics)

    app = build_graph()
    state = create_initial_state(user_instruction)

    final_state: Dict[str, Any] = dict(state)
    try:
        # "updates" dá o rastro por nó (logs); "values" dá o estado já reduzido
        # pelos reducers do LangGraph — é dele que sai o estado final correto.
        for mode, chunk in app.stream(
            state,
            config={"recursion_limit": GRAPH_RECURSION_LIMIT},
            stream_mode=["updates", "values"],
        ):
            if mode == "updates" and verbose:
                for node_name in chunk:
                    print(f"[Graph] nó '{node_name}' concluído.")
            elif mode == "values" and isinstance(chunk, dict):
                final_state = dict(chunk)
    except Exception as exc:  # noqa: BLE001 - inclui estouro do recursion_limit
        print(f"[Graph] Missão interrompida: {exc}")
        final_state["mission_status"] = MISSION_FAILED
        final_state.setdefault("failure_history", []).append(f"Grafo interrompido: {exc}")

    status = final_state.get("mission_status", MISSION_FAILED)
    if status not in (MISSION_SUCCESS, MISSION_FAILED):
        status = MISSION_FAILED
    metrics.finish(status)
    metrics.replan_count = max(metrics.replan_count, final_state.get("replan_count", 0))
    set_metrics(None)
    return final_state


if __name__ == "__main__":  # visualização rápida da topologia (Mermaid)
    print(build_graph().get_graph().draw_mermaid())
