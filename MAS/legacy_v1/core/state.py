import operator
from typing import Annotated, TypedDict, List, Dict, Any, Optional

class AgentState(TypedDict):
    # --- Contexto do Usuário e Missão ---
    user_intent: str                  # Comando inicial: "Vá à cozinha e pegue a chave"
    mission_status: str               # "in_progress", "success", "failed", "replanning"
    
    # --- Planejamento e Execução ---
    current_plan: List[str]           # Fila de tarefas pendentes
    current_step: Optional[str]       # Tarefa atualmente em execução
    
    # --- Telemetria e Hardware (Closed-Loop) ---
    robot_status: str                 # "idle", "moving", "blocked", "error"
    last_ros_feedback: Dict[str, Any] # Último payload recebido do ROS 2
    error_context: Optional[str]      # Descrição do último erro para o Planner
    replan_count: int                 # Contador de replanejamentos (erros contornados)
    
    # --- Histórico ---
    history: Annotated[List[str], operator.add] 
    
    # --- Roteamento ---
    next_node: str                    # "planner", "executor", "END"
