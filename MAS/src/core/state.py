"""
Estado compartilhado e constantes do Sistema Multi-Agente.

NOTA DE PROCEDENCIA: este arquivo foi reconstruido a partir de
src/core/__pycache__/state.cpython-310.pyc depois de ter sido sobrescrito por
engano. Constantes, campos do AgentState e a API da MissionMetrics conferem com
o bytecode. Os corpos dos metodos foram reescritos a partir das operacoes
observadas na desmontagem -- equivalentes, nao necessariamente identicos ao
original linha a linha.

O AgentState abaixo e a UNIAO dos campos das duas implementacoes que convivem
no projeto (total=False, entao nenhum no e obrigado a preencher tudo):
  * src/core/nodes.py + src/core/tools.py  -> usa user_instruction, plan, ...
  * src/agents/*      + src/tools/*        -> usa user_intent, current_plan, ...
"""

import csv
import datetime
import operator
import os
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage

# --------------------------------------------------------------------------- #
# Status de navegacao publicados pelo ROS 2
# --------------------------------------------------------------------------- #
STATUS_IDLE = "IDLE"
STATUS_RUNNING = "RUNNING"
STATUS_SUCCESS = "SUCCESS"
STATUS_PATH_BLOCKED = "PATH_BLOCKED"
STATUS_ERROR = "ERROR"

FAILURE_STATES = frozenset({STATUS_PATH_BLOCKED, STATUS_ERROR})
READY_STATES = frozenset({STATUS_IDLE, STATUS_SUCCESS})

# --------------------------------------------------------------------------- #
# Estados da missao
# --------------------------------------------------------------------------- #
MISSION_IN_PROGRESS = "in_progress"
MISSION_REPLANNING = "replanning"
MISSION_SUCCESS = "success"
MISSION_FAILED = "failed"

# --------------------------------------------------------------------------- #
# Nomes dos nos do grafo
# --------------------------------------------------------------------------- #
NODE_SUPERVISOR = "supervisor"
NODE_PLANNER = "planner"
NODE_EXECUTOR = "executor"
NODE_END = "END"

# Teto de replanejamentos antes de declarar a missao perdida.
MAX_REPLANS = int(os.environ.get("MAS_MAX_REPLANS", "3"))


class AgentState(TypedDict, total=False):
    """Estado global compartilhado por todos os nos do grafo."""

    # --- campos de src/core/nodes.py ---
    user_instruction: str
    plan: List[str]
    completed_tasks: Annotated[List[str], operator.add]
    current_subtask: Optional[str]
    navigation_status: str
    failure_history: Annotated[List[str], operator.add]
    messages: Annotated[List[BaseMessage], operator.add]
    plan_generated: bool
    decision_latency: float
    mission_start_ts: float

    # --- campos de src/agents/* ---
    user_intent: str
    current_plan: List[str]
    current_step: Optional[str]
    error_context: Optional[str]
    robot_status: str
    # Verdade fisica: so vira True quando uma tool de navegacao confirmou, via
    # TF, que o robo chegou. E o unico criterio de missao cumprida.
    last_nav_ok: bool
    # Busca: 'busca_vazia' marca que algum comodo foi olhado sem achar nada;
    # 'busca_ok' marca que a busca teve sucesso em algum comodo.
    busca_vazia: bool
    busca_ok: bool
    history: Annotated[List[str], operator.add]

    # --- comuns aos dois ---
    last_ros_feedback: Dict[str, Any]
    mission_status: str
    next_node: str
    replan_count: int


def create_initial_state(user_instruction: str) -> AgentState:
    """Monta o estado inicial de uma missao a partir do comando do usuario."""
    return {
        "user_instruction": user_instruction,
        "plan": [],
        "completed_tasks": [],
        "current_subtask": None,
        "navigation_status": STATUS_IDLE,
        "last_ros_feedback": {},
        "failure_history": [],
        "messages": [],
        "mission_status": MISSION_IN_PROGRESS,
        "next_node": "",
        "replan_count": 0,
        "plan_generated": False,
        "decision_latency": 0.0,
        "mission_start_ts": time.time(),
    }


class MissionMetrics:
    """Coletor de metricas de avaliacao de uma missao (TCR, FRR, latencia)."""

    def __init__(self, user_instruction: str, model_name: Optional[str] = None):
        self.user_instruction = user_instruction
        self.model_name = model_name or os.environ.get("OLLAMA_MODEL", "llama3.1")
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = MISSION_IN_PROGRESS
        self.decisions: List[Dict[str, Any]] = []
        self.replan_count = 0
        self.tool_calls = 0

        # --- Metricas da secao 8.3 do projeto ---------------------------
        # PL (Latencia de Planejamento): tempo que o Planejador leva para
        # decompor uma tarefa. Separa a decomposicao inicial dos replanejamentos.
        self.plan_latencies: List[float] = []
        self.replan_latencies: List[float] = []
        # AL (Latencia de Acao): tempo entre o Supervisor receber um feedback
        # de SUCESSO e despachar o proximo passo ao Executor.
        self.action_latencies: List[float] = []
        self._t_feedback: Optional[float] = None
        # Para a FRR: quantas falhas foram injetadas nesta missao.
        self.injected_faults = 0
        # Quantas vezes a guarda deterministica precisou corrigir a escolha de
        # ferramenta do LLM (mede a confiabilidade do tool calling).
        self.corrections: List[str] = []

    def record_decision(self, agent: str, latency: float, detail: str = "") -> None:
        """Registra a latencia de uma decisao tomada por um agente."""
        self.decisions.append({
            "agent": agent,
            "latency": round(latency, 3),
            "detail": detail,
            "t": round(time.time() - self.start_time, 3),
        })
        print(f"[METRICS] {agent}: decisao em {latency:.3f}s " + (f"| {detail}" if detail else ""))

    def record_replan(self) -> None:
        self.replan_count += 1

    def record_plan_latency(self, latency: float) -> None:
        """PL. A primeira medida e a decomposicao inicial; as demais, replanejamentos."""
        if not self.plan_latencies:
            self.plan_latencies.append(latency)
        else:
            self.replan_latencies.append(latency)

    def mark_feedback(self, t: float) -> None:
        """Marca o instante em que o Supervisor recebeu feedback de sucesso."""
        self._t_feedback = t

    def record_action_latency(self, t_dispatch: float) -> None:
        """AL. Fecha o intervalo feedback-de-sucesso -> despacho do proximo passo."""
        if self._t_feedback is not None:
            self.action_latencies.append(t_dispatch - self._t_feedback)
            self._t_feedback = None

    def record_injected_fault(self) -> None:
        self.injected_faults += 1

    def record_correction(self, motivo: str) -> None:
        self.corrections.append(motivo)

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    def finish(self, status: str) -> None:
        self.status = status
        self.end_time = time.time()

    @property
    def duration(self) -> float:
        return (self.end_time or time.time()) - self.start_time

    def latency_by_agent(self, agent: str) -> List[float]:
        return [d["latency"] for d in self.decisions if d["agent"] == agent]

    def avg_latency(self, agent: str) -> float:
        vals = self.latency_by_agent(agent)
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    @staticmethod
    def _media(vals, casas=4):
        return round(sum(vals) / len(vals), casas) if vals else 0.0

    @property
    def summary(self) -> Dict[str, Any]:
        todas = [d["latency"] for d in self.decisions]
        return {
            "status": self.status,
            "duration_seconds": round(self.duration, 2),
            "replan_count": self.replan_count,
            "injected_faults": self.injected_faults,
            "tool_calls": self.tool_calls,
            "decisions": len(self.decisions),
            "avg_decision_latency": round(sum(todas) / len(todas), 3) if todas else 0.0,
            "avg_supervisor_latency": self.avg_latency(NODE_SUPERVISOR),
            "avg_planner_latency": self.avg_latency(NODE_PLANNER),
            "avg_executor_latency": self.avg_latency(NODE_EXECUTOR),
            # Metricas nomeadas da secao 8.3
            "PL_plan_inicial_s": self._media(self.plan_latencies),
            "PL_replan_s": self._media(self.replan_latencies),
            "AL_acao_s": self._media(self.action_latencies, 6),
            "AL_amostras": len(self.action_latencies),
            "correcoes_guarda": len(self.corrections),
        }

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("[METRICAS DA MISSAO]")
        for k, v in self.summary.items():
            print(f"  {k:.<32} {v}")
        print("=" * 60)

    def save_csv(self, path: str = "metrics.csv") -> None:
        """Acrescenta uma linha ao CSV de avaliacao (cria o cabecalho se necessario)."""
        resumo = self.summary
        linha = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "model_name": self.model_name,
            "user_instruction": self.user_instruction,
            **resumo,
        }
        campos = ["timestamp", "model_name", "user_instruction"] + list(resumo.keys())

        # Se ja existe um CSV com cabecalho diferente (ex.: o formato antigo de
        # 6 colunas), arquiva o arquivo velho em vez de acrescentar linhas
        # desalinhadas embaixo de um cabecalho que nao corresponde.
        existe = os.path.isfile(path)
        if existe:
            with open(path, "r", newline="", encoding="utf-8") as f:
                cabecalho = next(csv.reader(f), [])
            if cabecalho != campos:
                arquivo = f"{os.path.splitext(path)[0]}_legado_{int(time.time())}.csv"
                os.rename(path, arquivo)
                print(f"[METRICS] Cabecalho antigo incompativel; CSV anterior movido para {arquivo}")
                existe = False

        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            if not existe:
                w.writeheader()
            w.writerow(linha)
        print(f"[METRICS] Linha registrada em {path}")
