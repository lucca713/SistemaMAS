from langgraph.graph import StateGraph, END
from src.core.state import AgentState
from src.agents.supervisor import supervise_node
from src.agents.planner import plan_node
from src.agents.executor import execute_node

def router(state: AgentState):
    """
    Função de roteamento condicional baseada na decisão do Supervisor.
    """
    next_node = state.get("next_node")
    if next_node == "END":
        return END
    return next_node

def build_graph():
    """
    Constrói e compila o grafo do Sistema Multi-Agente.
    """
    workflow = StateGraph(AgentState)
    
    # Adicionando os nós (Agentes)
    workflow.add_node("supervisor", supervise_node)
    workflow.add_node("planner", plan_node)
    workflow.add_node("executor", execute_node)
    
    # O ponto de entrada é sempre o Supervisor
    workflow.set_entry_point("supervisor")
    
    # Definindo as arestas condicionais a partir do Supervisor
    workflow.add_conditional_edges(
        "supervisor",
        router,
        {
            "planner": "planner",
            "executor": "executor",
            "supervisor": "supervisor", # Permite que o supervisor re-avalie o estado (polling)
            END: END
        }
    )
    
    # Arestas fixas: Planner e Executor sempre devolvem o controle para o Supervisor
    workflow.add_edge("planner", "supervisor")
    workflow.add_edge("executor", "supervisor")
    
    # Compilando o grafo
    app = workflow.compile()
    return app
