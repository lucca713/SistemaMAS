import os
import sys
from dotenv import load_dotenv

# Adiciona o diretório do sistema legado ao PATH do Python
LEGACY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ros2_ws_victor", "robot-agent", "ros2_ws", "src", "robot_agent"))
if LEGACY_DIR not in sys.path:
    sys.path.append(LEGACY_DIR)

# Agora podemos importar o módulo legado
from robot_tools import init_ros_node

from src.core.graph import build_graph
import langchain

# Ativar logs detalhados para ver exatamente o que o Ollama está fazendo
langchain.debug = True

# Carrega as variáveis de ambiente (como GEMINI_API_KEY) do arquivo .env
# Assumindo que seu arquivo se chama .env e está na pasta config
load_dotenv(dotenv_path="config/.env")

import time
import csv
import datetime

def main():
    print("Iniciando o Sistema Multi-Agente (LangGraph)...")
    
    # Inicializa o nó do ROS 2 do sistema legado
    print("Inicializando nó ROS 2...")
    init_ros_node()
    
    # Verifica se a chave da API foi carregada (o LangChain Google vai usar GOOGLE_API_KEY)
    if "GOOGLE_API_KEY" not in os.environ:
        print("AVISO: GOOGLE_API_KEY não encontrada nas variáveis de ambiente.")
        print("Certifique-se de que o arquivo config/.env possui essa variável.")
    
    # Construir a aplicação (grafo)
    app = build_graph()
    
    # Solicitando a intenção inicial do usuário via terminal
    print("\n" + "="*50)
    user_intent = input("Digite o comando para o robô (Task): ")
    print("="*50 + "\n")
    
    print(f"--- Intenção do Usuário: '{user_intent}' ---\n")
    
    # Estado inicial
    initial_state = {
        "user_intent": user_intent,
        "current_plan": [],
        "current_step": "",
        "history": [],
        "mission_status": "in_progress",
        "next_node": "",
        "replan_count": 0
    }
    
    # Nome do modelo sendo testado (pode configurar no .env ou hardcoded aqui para o teste)
    model_name = os.environ.get("TEST_MODEL_NAME", "Gemini_Modelo_1")
    
    start_time = time.time()
    final_status = "unknown"
    total_replans = 0
    
    # Executando o grafo
    for s in app.stream(initial_state):
        node_name = list(s.keys())[0]
        state_update = s[node_name]
        print(f"--- [MAIN] Nó '{node_name}' finalizou ---")
        if "mission_status" in state_update:
            final_status = state_update["mission_status"]
        if "replan_count" in state_update:
            total_replans = state_update["replan_count"]
            
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"\n[MÉTRICAS] Missão finalizada com status: {final_status}")
    print(f"[MÉTRICAS] Replanejamentos efetuados: {total_replans}")
    print(f"[MÉTRICAS] Tempo total: {duration:.2f} segundos")
    
    # Salvando no CSV
    csv_file = "metrics.csv"
    file_exists = os.path.isfile(csv_file)
    
    with open(csv_file, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["timestamp", "model_name", "user_intent", "duration_seconds", "status", "replan_count"])
        writer.writerow([
            datetime.datetime.now().isoformat(),
            model_name,
            user_intent,
            round(duration, 2),
            final_status,
            total_replans
        ])
    print(f"[MÉTRICAS] Dados salvos em {csv_file}")

if __name__ == "__main__":
    main()
