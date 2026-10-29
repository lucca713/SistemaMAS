from langchain_google_genai import ChatGoogleGenerativeAI
from src.core.state import AgentState
import time

def supervise_node(state: AgentState) -> dict:
    """
    Agente Supervisor:
    Analisa o estado atual, gerencia o ciclo fechado com o ROS 2 e
    decide quem deve ser chamado em seguida (Planner, Executor, ou fim).
    """
    print("--- [Supervisor] Avaliando estado... ---")
    
    current_plan = state.get("current_plan", [])
    current_step = state.get("current_step")
    mission_status = state.get("mission_status", "in_progress")
    
    # 1. Se não há plano e não há passo atual (Início ou Replanejamento)
    if not current_plan and not current_step:
        # Se tem histórico e não está replanejando, pode ser o fim da missão com sucesso.
        if state.get("history") and mission_status != "replanning":
             print("--- [Supervisor] Missão concluída! ---")
             return {"mission_status": "success", "next_node": "END"}
             
        print("--- [Supervisor] Sem plano. Encaminhando para Planner. ---")
        return {"next_node": "planner"}
        
    # 2. Se há um passo atualmente em execução, verifica o status (ROS 2 Closed-Loop)
    if current_step:
        # Aqui, no futuro, você consultaria o cliente ROS 2 de forma não bloqueante.
        # last_feedback = get_ros2_status() 
        # Vamos simular um retorno baseando-se no last_ros_feedback ou criar um mock
        
        last_feedback = state.get("last_ros_feedback", {})
        
        # --- Simulação temporária para testes se vazio ---
        if not last_feedback:
            print(f"--- [Supervisor] Aguardando conclusão do passo: '{current_step}' ---")
            # Simula que concluiu na primeira checagem para fluir o teste
            last_feedback = {"status": "success"} 
        # -----------------------------------------------
        
        if last_feedback.get("status") == "success":
            print(f"--- [Supervisor] Passo '{current_step}' concluído com sucesso. ---")
            return {
                "current_step": None,
                "last_ros_feedback": {}, # Limpa feedback para a próxima tarefa
                "next_node": "supervisor" # Retorna a si mesmo para despachar a próxima tarefa
            }
            
        elif last_feedback.get("status") in ["path_blocked", "error"]:
            reason = last_feedback.get("reason", "Erro desconhecido no hardware.")
            print(f"--- [Supervisor] FALHA DETECTADA: {reason}. ---")
            replan_count = state.get("replan_count", 0) + 1
            return {
                "error_context": f"Falha no passo '{current_step}': {reason}",
                "current_plan": [], # Invalida o plano restante
                "current_step": None,
                "mission_status": "replanning",
                "replan_count": replan_count,
                "next_node": "planner" # Dispara o replanejamento
            }
        else:
            # Ainda em andamento. Aguarda antes de checar novamente para não sobrecarregar.
            print(f"--- [Supervisor] Passo '{current_step}' em andamento... ---")
            time.sleep(1)
            return {"next_node": "supervisor"} 
            
    # 3. Se não há passo atual, mas tem plano, despacha o próximo para o executor
    if current_plan:
        next_step = current_plan.pop(0)
        print(f"--- [Supervisor] Despachando passo para Executor: '{next_step}'. Passos restantes: {len(current_plan)} ---")
        
        return {
            "current_step": next_step,
            "current_plan": current_plan,
            "last_ros_feedback": {}, # Limpa para garantir nova leitura
            "next_node": "executor"
        }
        
    # 4. Fallback de missão concluída
    print("--- [Supervisor] Missão concluída! ---")
    return {"mission_status": "success", "next_node": "END"}
