from langchain_ollama import ChatOllama
from langchain_core.prompts import PromptTemplate
from src.core.state import AgentState
import json
import time

# Importar a ferramenta
from robot_tools import navigate_to

def execute_node(state: AgentState) -> dict:
    """
    Agente de Execução:
    Recebe um único passo do Supervisor e o executa chamando o ROS 2.
    """
    print("--- [Executor] Trabalhando... ---")
    
    current_step = state.get("current_step")
    print(f"--- [Executor] Traduzindo passo para ação real: '{current_step}' ---")
    
    # Inicializando o LLM do Ollama
    llm = ChatOllama(model="llama3.1", temperature=0)
    
    prompt = PromptTemplate.from_template("""
Você é o sistema de execução de um robô de serviço.
A ação que você precisa executar é: '{step}'

Classifique a ação em uma destas categorias e extraia o alvo:
1. Se for navegação autônoma (ir até um lugar): Responda "NAVIGATE: [nome_do_lugar]" (Destinos válidos: origem, vermelho, azul, parede_norte, bloco).
2. Se for dar ré: Responda "MANUAL: backward"
3. Se for girar para a esquerda: Responda "MANUAL: left"
4. Se for girar para a direita: Responda "MANUAL: right"
5. Se for ir para frente (curto espaço): Responda "MANUAL: forward"

Responda APENAS com a categoria e o alvo. Exemplo: "NAVIGATE: bloco" ou "MANUAL: backward". Sem pontuação.
""")
    
    print(f"--- [Executor] Enviando para o Ollama local (Modo Turbo)... ---")
    try:
        chain = prompt | llm
        result = chain.invoke({"step": current_step})
        
        # Pega a resposta limpa da IA
        ia_decision = result.content.strip()
        print(f"--- [Executor] A IA decidiu: '{ia_decision}'. Executando via ROS 2! ---")
        
        # Roteamento
        if "MANUAL:" in ia_decision.upper():
            direction = ia_decision.split(":")[1].strip().lower()
            from robot_tools import move_robot
            json_param = json.dumps({"direction": direction})
            tool_output = move_robot.invoke({"input_str": json_param})
            
            feedback_status = "error" if "error" in tool_output.lower() else "success"
            feedback_msg = tool_output
            
        else:
            # Padrão: Navigate
            goal_name = ia_decision.split(":")[-1].strip().lower()
            if "bloco" in goal_name: goal_name = "bloco"
            elif "porta" in goal_name: goal_name = "porta"
            
            json_param = json.dumps({"room": goal_name})
            tool_output = navigate_to.invoke({"input_str": json_param})
            
            # Pausa ativa aguardando o resultado do Nav2 no tópico /nav_result
            print(f"--- [Executor] Aguardando confirmação real do robô (Nav2)... ---")
            
            import rclpy
            from rclpy.node import Node
            from std_msgs.msg import String
            import threading

            feedback_status = "error"
            feedback_msg = "Timeout esperando resposta do Nav2"
            
            class NavResultListener(Node):
                def __init__(self):
                    super().__init__('nav_result_listener_temp')
                    self.subscription = self.create_subscription(String, 'nav_result', self.listener_callback, 10)
                    self.received_msg = None

                def listener_callback(self, msg):
                    self.received_msg = msg.data

            listener_node = NavResultListener()
            
            # Espera até 60 segundos pela resposta
            timeout = 60
            start_time = time.time()
            while rclpy.ok() and (time.time() - start_time) < timeout:
                rclpy.spin_once(listener_node, timeout_sec=0.1)
                if listener_node.received_msg:
                    if "success" in listener_node.received_msg:
                        feedback_status = "success"
                        feedback_msg = f"Robot arrived successfully: {listener_node.received_msg}"
                    elif "canceled" in listener_node.received_msg:
                        feedback_status = "error"
                        feedback_msg = f"Robot navigation was canceled: {listener_node.received_msg}"
                    else:
                        feedback_status = "error"
                        feedback_msg = f"Robot failed to navigate: {listener_node.received_msg}"
                    break
                    
            listener_node.destroy_node()
    except Exception as e:
        feedback_status = "error"
        feedback_msg = str(e)
        print(f"--- [Executor] Erro na execução: {e} ---")
    
    print(f"--- [Executor] Feedback do ambiente: {feedback_status} | Resposta: {feedback_msg} ---")
    
    return {
        "history": [f"Executado: {current_step} -> {feedback_status} ({feedback_msg})"],
        "last_ros_feedback": {"status": feedback_status, "reason": feedback_msg}
    }

