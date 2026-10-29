"""
Nós do grafo cognitivo: Supervisor, Planejador e Executor.

Divisão de responsabilidades:
  * Supervisor  -> orquestração determinística (rápida, sem LLM) sobre a telemetria ROS 2;
  * Planejador  -> raciocínio abstrato com LLM local via Ollama (decomposição e "Plano B");
  * Executor    -> padrão ReAct sobre o Toolkit, sem gerar código ROS 2 bruto.

A inferência roda 100% local (Ollama), sem custo de API. Se o servidor do Ollama não
estiver no ar (ou com `MAS_OFFLINE=1`), Planejador e Executor caem em heurísticas
determinísticas equivalentes, para que o pipeline continue testável.
"""

import os
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.core.state import (
    FAILURE_STATES,
    MAX_REPLANS,
    MISSION_FAILED,
    MISSION_IN_PROGRESS,
    MISSION_REPLANNING,
    MISSION_SUCCESS,
    NODE_END,
    NODE_EXECUTOR,
    NODE_PLANNER,
    NODE_SUPERVISOR,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_PATH_BLOCKED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    AgentState,
    MissionMetrics,
)
from src.core.tools import ROBOT_TOOLKIT, available_rooms, get_bridge, resolve_room

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))
EXECUTOR_RECURSION_LIMIT = int(os.environ.get("MAS_EXECUTOR_RECURSION_LIMIT", "12"))

# --------------------------------------------------------------------------- #
# Métricas (registro global da missão corrente)
# --------------------------------------------------------------------------- #
_METRICS: Optional[MissionMetrics] = None


def set_metrics(metrics: Optional[MissionMetrics]) -> None:
    """Associa um coletor de métricas à execução corrente do grafo."""
    global _METRICS
    _METRICS = metrics


def get_metrics() -> Optional[MissionMetrics]:
    return _METRICS


def _record(agent: str, latency: float, detail: str = "") -> None:
    if _METRICS is not None:
        _METRICS.record_decision(agent, latency, detail)
    else:
        print(f"[METRICS] {agent}: decisão em {latency:.3f}s {('| ' + detail) if detail else ''}")


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
_ollama_online: Optional[bool] = None


def ollama_available(force_check: bool = False) -> bool:
    """Verifica (uma vez por processo) se o servidor do Ollama está no ar."""
    global _ollama_online
    if _ollama_online is not None and not force_check:
        return _ollama_online

    import urllib.request

    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=3) as resp:
            _ollama_online = resp.status == 200
    except Exception as exc:  # noqa: BLE001
        print(f"[LLM] Ollama indisponível em {OLLAMA_BASE_URL} ({exc}).")
        _ollama_online = False
    return _ollama_online


def _offline() -> bool:
    """True quando os agentes devem usar heurísticas em vez do LLM."""
    if os.environ.get("MAS_OFFLINE") == "1":
        return True
    return not ollama_available()


def get_llm(temperature: float = 0.0):
    """Instancia o LLM local (Ollama) usado pelos agentes de raciocínio."""
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
        client_kwargs={"timeout": OLLAMA_TIMEOUT},
    )


class MissionPlan(BaseModel):
    """Saída estruturada do Agente Planejador."""

    subtasks: List[str] = Field(
        description="Lista ordenada de subtarefas atômicas, uma ação por item."
    )
    rationale: str = Field(default="", description="Justificativa curta do plano.")


# --------------------------------------------------------------------------- #
# 1. AGENTE SUPERVISOR
# --------------------------------------------------------------------------- #
def supervisor_node(state: AgentState) -> Dict[str, Any]:
    """
    Gerente de estado e orquestrador. É o nó de entrada do grafo.

    Decide, a partir do status do ROS 2:
      * SUCCESS/IDLE + subtarefas pendentes -> despacha a próxima ao Executor;
      * PATH_BLOCKED/ERROR                  -> intercepta a falha e aciona o Planejador;
      * plano vazio e missão cumprida       -> encerra o grafo.
    """
    t0 = time.time()
    status = state.get("navigation_status", STATUS_IDLE)
    plan: List[str] = list(state.get("plan") or [])
    current_subtask = state.get("current_subtask", "")
    replan_count = state.get("replan_count", 0)
    completed = state.get("completed_tasks") or []

    print(f"\n--- [Supervisor] status={status} | pendentes={len(plan)} | concluídas={len(completed)} ---")

    # --- 1. Falha detectada: intercepta e impede o abortamento da missão ----- #
    if status in FAILURE_STATES:
        feedback = get_bridge().get_feedback().get("raw", "")
        failure = f"Falha em '{current_subtask or 'subtarefa desconhecida'}' ({status}): {feedback}"

        if replan_count >= MAX_REPLANS:
            print(f"--- [Supervisor] Limite de {MAX_REPLANS} replanejamentos atingido. Abortando. ---")
            latency = time.time() - t0
            _record(NODE_SUPERVISOR, latency, "aborto por limite de replanejamentos")
            return {
                "mission_status": MISSION_FAILED,
                "next_node": NODE_END,
                "failure_history": [failure + " | limite de replanejamentos excedido"],
                "decision_latency": latency,
            }

        print(f"--- [Supervisor] FALHA INTERCEPTADA -> Planejador (replan #{replan_count + 1}) ---")
        latency = time.time() - t0
        _record(NODE_SUPERVISOR, latency, f"falha {status} -> replanejamento")
        if _METRICS is not None:
            _METRICS.record_replan()
        return {
            "plan": [],                       # invalida o plano restante
            "current_subtask": "",
            "mission_status": MISSION_REPLANNING,
            "replan_count": replan_count + 1,
            "failure_history": [failure],
            "navigation_status": STATUS_IDLE,  # falha já consumida
            "next_node": NODE_PLANNER,
            "decision_latency": latency,
        }

    # --- 2. Ainda em execução: mantém a malha fechada aguardando o ROS 2 ----- #
    if status == STATUS_RUNNING and current_subtask:
        live_status = get_bridge().get_status()
        if live_status == STATUS_RUNNING:
            print(f"--- [Supervisor] '{current_subtask}' em andamento; aguardando ROS 2... ---")
            time.sleep(0.5)
            latency = time.time() - t0
            return {"next_node": NODE_SUPERVISOR, "decision_latency": latency}
        return {"navigation_status": live_status, "next_node": NODE_SUPERVISOR}

    # --- 3. Sem plano: decompor a instrução original ------------------------ #
    if not plan and not state.get("plan_generated", False):
        print("--- [Supervisor] Nenhum plano ainda -> Planejador (decomposição inicial) ---")
        latency = time.time() - t0
        _record(NODE_SUPERVISOR, latency, "decomposição inicial")
        return {"next_node": NODE_PLANNER, "decision_latency": latency}

    # --- 4. Plano esgotado: missão concluída -------------------------------- #
    if not plan:
        print(f"--- [Supervisor] Missão concluída: {len(completed)} subtarefa(s). ---")
        latency = time.time() - t0
        _record(NODE_SUPERVISOR, latency, "missão concluída")
        return {
            "mission_status": MISSION_SUCCESS,
            "current_subtask": "",
            "next_node": NODE_END,
            "decision_latency": latency,
        }

    # --- 5. Despacha a próxima subtarefa ao Executor ------------------------ #
    next_subtask, remaining = plan[0], plan[1:]
    get_bridge().reset_status()
    print(f"--- [Supervisor] Despachando: '{next_subtask}' (restam {len(remaining)}) ---")
    latency = time.time() - t0
    _record(NODE_SUPERVISOR, latency, f"despacho: {next_subtask}")
    return {
        "current_subtask": next_subtask,
        "plan": remaining,
        "navigation_status": STATUS_RUNNING,
        "mission_status": MISSION_IN_PROGRESS,
        "next_node": NODE_EXECUTOR,
        "decision_latency": latency,
    }


# --------------------------------------------------------------------------- #
# 2. AGENTE PLANEJADOR
# --------------------------------------------------------------------------- #
PLANNER_SYSTEM = """Você é o Agente Planejador de um robô doméstico de serviço da RoboCup@Home.
Decomponha a instrução do usuário em subtarefas ATÔMICAS, na ordem de execução.

Regras:
1. Cada subtarefa deve corresponder a UMA única ação executável pelo robô
   (navegar até um lugar, procurar alguém, falar com o usuário, consultar as regras).
2. Seja o mais conciso possível: nada de passos redundantes ou de verificação.
3. Destinos de navegação válidos no mapa atual: {rooms}.
   Use sempre um desses nomes ao pedir navegação.
4. Escreva cada subtarefa em português, no imperativo (ex.: "ir até a cozinha").

{replan_block}"""

REPLAN_BLOCK = """ATENÇÃO — REPLANEJAMENTO (Plano B):
A execução falhou. Histórico de falhas:
{failures}

Subtarefas já concluídas (NÃO as repita): {completed}
Destinos que JÁ FALHARAM em tentativas anteriores: {failed_destinations}

Regras OBRIGATÓRIAS do Plano B:
  a) O primeiro passo é SEMPRE uma manobra de desvencilhamento
     ("dar ré" ou "girar para a direita"), pois o robô pode estar preso.
  b) NUNCA repita como segundo passo o destino que acabou de falhar.
  c) Se um destino já falhou, ir direto nele de novo NÃO é um Plano B.
     Vá primeiro a um cômodo INTERMEDIÁRIO diferente (para abordar por outro caminho)
     e só então tente o destino final novamente.
  d) Termine com as subtarefas que ainda faltam da missão.

Exemplo, quando "Kitchen Counter" já falhou:
  ["dar ré", "ir até Dining Room Table", "ir até Kitchen Counter", "falar com o usuário"]
Exemplo ERRADO (repete o destino que falhou logo após a manobra):
  ["dar ré", "ir até Kitchen Counter", "falar com o usuário"]"""


def _failed_destinations(failure_history: List[str]) -> List[str]:
    """Extrai do histórico de falhas os destinos do mapa que já não deram certo."""
    failed: List[str] = []
    for entry in failure_history:
        for room in available_rooms():
            if room.lower() in entry.lower() and room not in failed:
                failed.append(room)
    return failed


MANEUVER_HINTS = ("ré", "re ", "recu", "gir", "vir", "rotac", "tras")


def _is_maneuver(subtask: str) -> bool:
    text = subtask.lower()
    return any(hint in text for hint in MANEUVER_HINTS)


def _mentions(subtask: str, room: str) -> bool:
    """True se a subtarefa se refere a esse destino do mapa."""
    text = subtask.lower()
    if room.lower() in text:
        return True
    resolved = resolve_room(text)
    return resolved == room


def _enforce_replan_policy(plan: List[str], failed: List[str]) -> List[str]:
    """
    Garante que o Plano B seja de fato um plano B, mesmo quando o LLM local
    devolve praticamente o mesmo plano que falhou.

    Aplica duas regras determinísticas:
      1. o plano começa por uma manobra de desvencilhamento;
      2. um destino que já falhou só é tentado DEPOIS de passar por um
         cômodo intermediário diferente (aborda o local por outro caminho).
    """
    if not plan:
        return plan

    adjusted = list(plan)
    if not _is_maneuver(adjusted[0]):
        adjusted.insert(0, "dar ré")
        print("--- [Planejador] Política de replanejamento: manobra de ré inserida. ---")

    if not failed:
        return adjusted

    alternativas = [r for r in available_rooms() if r not in failed]
    if not alternativas:
        return adjusted

    resultado: List[str] = []
    visitou_intermediario = False
    for subtask in adjusted:
        repete_falha = any(_mentions(subtask, room) for room in failed)
        if repete_falha and not visitou_intermediario:
            waypoint = alternativas[0]
            resultado.append(f"ir até {waypoint}")
            visitou_intermediario = True
            print(
                f"--- [Planejador] Política de replanejamento: waypoint '{waypoint}' "
                f"inserido antes de repetir um destino que falhou. ---"
            )
        elif not repete_falha and not _is_maneuver(subtask) and resolve_room(subtask):
            visitou_intermediario = True
        resultado.append(subtask)
    return resultado


def _extract_destination(instruction: str) -> str:
    """Encontra na instrução o primeiro destino que existe no mapa do Nav2."""
    from src.core.tools import ROOM_ALIASES

    text = instruction.lower()
    candidates = [c for c in ROOM_ALIASES if c in text]
    candidates += [r for r in available_rooms() if r.lower().split()[0] in text]
    for candidate in candidates:
        resolved = resolve_room(candidate)
        if resolved:
            return resolved
    rooms = available_rooms()
    return rooms[0] if rooms else "sala"


def _heuristic_plan(instruction: str, is_replan: bool) -> List[str]:
    """Plano de contingência determinístico (usado quando o LLM está indisponível)."""
    destino = _extract_destination(instruction)
    if is_replan:
        return ["dar ré", "girar para a direita", f"ir até {destino}"]
    return [f"ir até {destino}", "avisar o usuário que a tarefa foi concluída"]


def planner_node(state: AgentState) -> Dict[str, Any]:
    """
    Decompositor e estrategista.

    Em regime normal, transforma o comando do usuário em subtarefas atômicas.
    Acionado pelo Supervisor após uma falha, consome `failure_history` e gera um
    "Plano B" em tempo real, escolhendo manobras e rotas alternativas.
    """
    t0 = time.time()
    instruction = state.get("user_instruction", "")
    failures = state.get("failure_history") or []
    completed = state.get("completed_tasks") or []
    is_replan = state.get("mission_status") == MISSION_REPLANNING or bool(failures)

    modo = "REPLANEJAMENTO (Plano B)" if is_replan else "decomposição inicial"
    print(f"--- [Planejador] {modo} para: '{instruction}' ---")

    replan_block = (
        REPLAN_BLOCK.format(
            failures="\n".join(f"- {f}" for f in failures[-5:]),
            completed=completed or "nenhuma",
            failed_destinations=_failed_destinations(failures) or "nenhum",
        )
        if is_replan
        else ""
    )

    if _offline():
        subtasks = _heuristic_plan(instruction, is_replan)
        print("--- [Planejador] LLM indisponível; usando plano heurístico. ---")
    else:
        system = PLANNER_SYSTEM.format(rooms=available_rooms(), replan_block=replan_block)
        try:
            llm = get_llm(temperature=0.0).with_structured_output(MissionPlan)
            result: MissionPlan = llm.invoke(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Instrução original do usuário: {instruction}"},
                ]
            )
            subtasks = [s.strip() for s in result.subtasks if s and s.strip()]
            if result.rationale:
                print(f"--- [Planejador] Racional: {result.rationale} ---")
        except Exception as exc:  # noqa: BLE001 - uma falha do LLM não pode travar a missão
            print(f"--- [Planejador] Erro no LLM ({exc}); usando plano heurístico. ---")
            subtasks = _heuristic_plan(instruction, is_replan)

    if is_replan and subtasks:
        subtasks = _enforce_replan_policy(subtasks, _failed_destinations(failures))

    if not subtasks:
        latency = time.time() - t0
        _record(NODE_PLANNER, latency, "plano vazio")
        return {
            "plan": [],
            "plan_generated": True,
            "mission_status": MISSION_FAILED,
            "next_node": NODE_SUPERVISOR,
            "failure_history": ["Planejador não conseguiu gerar um plano viável."],
        }

    latency = time.time() - t0
    print(f"--- [Planejador] Plano ({len(subtasks)} passos): {subtasks} ---")
    _record(NODE_PLANNER, latency, modo)
    return {
        "plan": subtasks,
        "plan_generated": True,
        "current_subtask": "",
        "mission_status": MISSION_IN_PROGRESS,
        "navigation_status": STATUS_IDLE,
        "next_node": NODE_SUPERVISOR,
        "decision_latency": latency,
    }


# --------------------------------------------------------------------------- #
# 3. AGENTE EXECUTOR (ReAct)
# --------------------------------------------------------------------------- #
EXECUTOR_SYSTEM = """Você é o Agente Executor de um robô doméstico ROS 2 da RoboCup@Home.
Você recebe UMA subtarefa e a cumpre chamando as ferramentas disponíveis.

Regras:
1. NUNCA escreva ou invente código ROS 2: use exclusivamente as ferramentas.
2. Chame apenas as ferramentas necessárias para esta subtarefa e pare.
3. Destinos de navegação válidos: {rooms}.
4. Se uma ferramenta retornar PATH_BLOCKED ou ERROR, NÃO fique tentando de novo:
   relate o resultado e encerre — o Supervisor cuidará do replanejamento.
5. Chame UMA ferramenta por vez e nunca a mesma ferramenta duas vezes seguidas.
6. Ao terminar, responda em uma frase curta dizendo o que foi feito e o resultado."""


def _heuristic_execute(subtask: str) -> str:
    """Despacho determinístico de ferramenta (usado quando o LLM está indisponível)."""
    from src.core.tools import (
        tool_navigateTo,
        tool_queryKnowledgeBase,
        tool_reverseRobot,
        tool_rotateRobot,
        tool_speakToUser,
    )

    text = subtask.lower()
    if "ré" in text or "re " in text or "recu" in text or "tras" in text:
        return tool_reverseRobot.invoke({"duration_seconds": 2.0, "speed": 0.2})
    if "gir" in text or "vir" in text or "rotac" in text:
        speed = -0.5 if "direita" in text else 0.5
        return tool_rotateRobot.invoke({"duration_seconds": 1.5, "angular_speed": speed})
    if "regra" in text or "consult" in text:
        return tool_queryKnowledgeBase.invoke({"query": subtask})
    if "fal" in text or "avis" in text or "diga" in text or "inform" in text:
        return tool_speakToUser.invoke({"text": subtask})
    destino = subtask
    for prefixo in ("ir até o ", "ir até a ", "ir até ", "ir para o ", "ir para a ", "ir ao ", "ir à ", "navegar até "):
        if prefixo in text:
            destino = subtask[text.index(prefixo) + len(prefixo):]
            break
    return tool_navigateTo.invoke({"room": destino.strip()})


def executor_node(state: AgentState) -> Dict[str, Any]:
    """
    Executa a subtarefa atômica despachada pelo Supervisor usando o paradigma ReAct:
    raciocina sobre a subtarefa, escolhe a ferramenta Python adequada e publica o
    resultado de volta no grafo.
    """
    t0 = time.time()
    subtask = state.get("current_subtask", "")
    bridge = get_bridge()
    print(f"--- [Executor] Executando: '{subtask}' ---")

    new_messages: List[Any] = []
    try:
        if _offline():
            output = _heuristic_execute(subtask)
            print("--- [Executor] LLM indisponível; despacho heurístico de ferramenta. ---")
        else:
            from langchain_core.messages import HumanMessage
            from langgraph.prebuilt import create_react_agent

            agent = create_react_agent(
                get_llm(temperature=0.0),
                ROBOT_TOOLKIT,
                prompt=EXECUTOR_SYSTEM.format(rooms=available_rooms()),
            )
            result = agent.invoke(
                {"messages": [HumanMessage(content=f"Subtarefa a executar: {subtask}")]},
                config={"recursion_limit": EXECUTOR_RECURSION_LIMIT},
            )
            new_messages = result.get("messages", [])
            output = new_messages[-1].content if new_messages else ""
            if _METRICS is not None:
                _METRICS.tool_calls += sum(
                    len(getattr(m, "tool_calls", []) or []) for m in new_messages
                )
    except Exception as exc:  # noqa: BLE001
        # Falha de infraestrutura do LLM não é falha do robô: tenta o despacho
        # determinístico antes de reportar erro ao Supervisor.
        print(f"--- [Executor] Erro no agente ReAct ({exc}); tentando despacho heurístico. ---")
        try:
            output = _heuristic_execute(subtask)
        except Exception as inner:  # noqa: BLE001 - aí sim vira falha tratável no grafo
            print(f"--- [Executor] Erro na execução: {inner} ---")
            bridge.set_status(STATUS_ERROR, f"exceção no Executor: {inner}")
            output = f"ERROR: {inner}"

    # Fecha a malha: o status real vem do ROS 2, não da narrativa do LLM.
    status = bridge.get_status()
    if status == STATUS_RUNNING:
        # Nenhuma ferramenta de navegação foi acionada (ex.: fala, consulta ao RAG).
        status = STATUS_ERROR if str(output).upper().startswith("ERROR") else STATUS_SUCCESS
        bridge.set_status(status, str(output)[:200])

    latency = time.time() - t0
    feedback = bridge.get_feedback()
    print(f"--- [Executor] Resultado: {status} | {str(output)[:160]} ---")
    _record(NODE_EXECUTOR, latency, f"{subtask} -> {status}")

    update: Dict[str, Any] = {
        "navigation_status": status,
        "last_ros_feedback": feedback,
        "next_node": NODE_SUPERVISOR,
        "decision_latency": latency,
    }
    if new_messages:
        update["messages"] = new_messages
    if status == STATUS_SUCCESS:
        update["completed_tasks"] = [subtask]
    return update
