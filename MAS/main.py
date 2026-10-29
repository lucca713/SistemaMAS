"""
Ponto de entrada do Sistema Multi-Agente (LangGraph + Ollama local).

O Gemini saiu: Planejador e Executor rodam 100% em Ollama. O nome do modelo
gravado no CSV agora e o modelo que de fato rodou -- antes a coluna dizia
"Gemini_Modelo_1" enquanto o codigo chamava llama3.1.

Usa o grafo de src/agents/graph.py e a MissionMetrics de src/core/state.py.
"""

import os
import time

from dotenv import load_dotenv

from src.agents._metrics import set_metrics
from src.agents.graph import build_graph
from src.core.state import (
    MISSION_FAILED,
    MISSION_IN_PROGRESS,
    MISSION_SUCCESS,
    MissionMetrics,
)
from src.tools.ros_bridge import GOALS_FILE, get_bridge, shutdown_bridge

load_dotenv(dotenv_path="config/.env")

MODELO = os.environ.get("MAS_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1"))


def main():
    print("Iniciando o Sistema Multi-Agente (LangGraph + Ollama)...")
    print(f"Modelo: {MODELO}")

    print("Inicializando ponte ROS 2...")
    ponte = get_bridge()
    print(f"Metas carregadas de {GOALS_FILE}")
    print(f"Destinos disponiveis: {', '.join(ponte.goals)}")

    if ponte.room_pub.get_subscription_count() == 0:
        print("AVISO: ninguem esta inscrito em /room.")
        print("       Suba o no de navegacao:  ros2 run robot_bringup navigate_to_goal")

    pose = ponte.map_pose()
    if pose is None:
        print("AVISO: TF map->base_link indisponivel. SLAM/Nav2 ja estao no ar?")
        print("       Sem TF nao da para confirmar chegada: toda navegacao sera reportada como falha.")
    else:
        print(f"Pose inicial do robo: x={pose[0]:.2f}, y={pose[1]:.2f}")

    app = build_graph()

    print("\n" + "=" * 50)
    intent = input("Digite o comando para o robo (Task): ")
    print("=" * 50 + "\n")

    metrics = MissionMetrics(intent, model_name=MODELO)
    set_metrics(metrics)

    estado_inicial = {
        "user_intent": intent,
        "current_plan": [],
        "current_step": None,
        "history": [],
        "mission_status": MISSION_IN_PROGRESS,
        "next_node": "",
        "replan_count": 0,
        "last_nav_ok": False,
        "last_ros_feedback": {},
        "error_context": None,
        "mission_start_ts": time.time(),
    }

    status_final = MISSION_FAILED
    motivo_final = ""

    try:
        # recursion_limit alto: o ciclo supervisor -> executor -> supervisor
        # gasta varios passos do grafo por acao fisica do robo.
        for s in app.stream(estado_inicial, config={"recursion_limit": 100}):
            no = list(s.keys())[0]
            upd = s[no] or {}
            print(f"--- [MAIN] No '{no}' finalizou ---")
            if "mission_status" in upd:
                status_final = upd["mission_status"]
            if upd.get("error_context"):
                motivo_final = upd["error_context"]
    except Exception as e:
        status_final = MISSION_FAILED
        motivo_final = f"Grafo interrompido: {e}"
        print(f"[ERRO] {motivo_final}")

    if status_final not in (MISSION_SUCCESS, MISSION_FAILED):
        status_final = MISSION_FAILED

    metrics.finish(status_final)

    if status_final != MISSION_SUCCESS and motivo_final:
        print(f"\n[MOTIVO DA FALHA] {motivo_final}")

    pose = ponte.map_pose()
    if pose:
        print(f"[POSE FINAL] x={pose[0]:.2f}, y={pose[1]:.2f}")
        for nome in ponte.goals:
            d = ponte._distance_to_goal(nome)
            if d is not None:
                print(f"             distancia ate '{nome}': {d:.2f} m")

    metrics.print_summary()
    metrics.save_csv("metrics.csv")

    set_metrics(None)
    shutdown_bridge()


if __name__ == "__main__":
    main()
