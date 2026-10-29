"""
Toolkit de integração ROS 2 <-> LangChain.

Os agentes NUNCA geram código ROS 2 bruto: eles invocam as funções decoradas com
`@tool` deste módulo, que encapsulam publishers/subscribers do ROS 2 Humble.

Ponte (`Ros2Bridge`):
  * publica metas de navegação no tópico `room` (consumido por navigate_to_goal.py,
    que fala com o Nav2 via action `navigate_to_pose`);
  * publica velocidades no `/cmd_vel` para manobras de desvencilhamento;
  * escuta `/navigation_status` (e o tópico legado `nav_result`) para fechar a malha.

Se o `rclpy` não estiver disponível (ambiente sem ROS sourceado) ou se
`MAS_SIMULATION=1`, a ponte entra em modo simulado — o que também permite injetar
falhas determinísticas para medir a resiliência do sistema:

    MAS_SIMULATION=1  MAS_FAULT_ROOMS="cozinha,bloco"  python main.py
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from src.core.state import (
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_PATH_BLOCKED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
)

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
TOPIC_ROOM = os.environ.get("MAS_TOPIC_ROOM", "room")
TOPIC_NAV_STATUS = os.environ.get("MAS_TOPIC_NAV_STATUS", "/navigation_status")
TOPIC_NAV_RESULT = os.environ.get("MAS_TOPIC_NAV_RESULT", "nav_result")  # legado
TOPIC_CMD_VEL = os.environ.get("MAS_TOPIC_CMD_VEL", "/cmd_vel")
TOPIC_TTS = os.environ.get("MAS_TOPIC_TTS", "/tts")

NAV_TIMEOUT = float(os.environ.get("MAS_NAV_TIMEOUT", "90"))
SIM_NAV_DURATION = float(os.environ.get("MAS_SIM_NAV_DURATION", "1.0"))

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_GOAL_FILES = [
    os.path.join(_BASE_DIR, "..", "ros2_ws_vinicius", "src", "robot_bringup", "config", "goals.json"),
    os.path.join(_BASE_DIR, "..", "ros2_ws_vinicius", "src", "robot_bringup", "config", "goalsTest.json"),
]

# Apelidos PT-BR -> termo usado nas chaves do goals.json
ROOM_ALIASES = {
    "cozinha": "kitchen",
    "sala": "living room",
    "sala de estar": "living room",
    "sala de jantar": "dining room",
    "quarto": "bedroom",
    "dormitorio": "bedroom",
    "banheiro": "bathroom",
    "corredor": "hall",
    "hall": "hall",
    "garagem": "garage",
    "lavanderia": "laundry",
    "mesa": "table",
    "lixo": "trash",
    "armario": "wardrobe",
    "guarda-roupa": "wardrobe",
}


def _load_goals() -> Dict[str, Dict[str, float]]:
    """Carrega o mapa nome_do_cômodo -> coordenada usado pelo Nav2."""
    candidates: List[str] = []
    env_file = os.environ.get("MAS_NAV_GOALS_FILE")
    if env_file:
        candidates.append(env_file)
    candidates.extend(_DEFAULT_GOAL_FILES)

    goals: Dict[str, Dict[str, float]] = {}
    for path in candidates:
        path = os.path.abspath(path)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fp:
                    goals.update(json.load(fp))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[Toolkit] Aviso: não foi possível ler '{path}': {exc}")
    if not goals:
        print("[Toolkit] Aviso: nenhum arquivo de goals encontrado; a validação de cômodos fica desativada.")
    return goals


GOALS = _load_goals()


def _strip_accents(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def resolve_room(room: str) -> Optional[str]:
    """
    Traduz o nome de um cômodo em linguagem natural para a chave exata
    esperada pelo nó de navegação (ex.: "cozinha" -> "Kitchen Counter").
    Retorna None se o destino não existir no mapa.
    """
    if not room:
        return None
    query = _strip_accents(room.lower().strip())
    if not GOALS:  # sem arquivo de metas: repassa o nome cru para o ROS 2
        return room.strip()

    keys = list(GOALS.keys())
    # 1. Correspondência exata (case-insensitive)
    for key in keys:
        if _strip_accents(key.lower()) == query:
            return key
    # 2. Tradução por apelido PT-BR
    for alias, term in ROOM_ALIASES.items():
        if alias in query:
            for key in keys:
                if term in key.lower():
                    return key
    # 3. Correspondência parcial
    for key in keys:
        key_norm = _strip_accents(key.lower())
        if query in key_norm or key_norm in query:
            return key
    return None


def available_rooms() -> List[str]:
    return list(GOALS.keys())


# --------------------------------------------------------------------------- #
# Ponte ROS 2
# --------------------------------------------------------------------------- #
class Ros2Bridge:
    """Singleton que concentra toda a comunicação com o ROS 2."""

    _instance: Optional["Ros2Bridge"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "Ros2Bridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self.simulated = os.environ.get("MAS_SIMULATION", "0") == "1"
        self._status = STATUS_IDLE
        self._last_feedback: Dict[str, Any] = {}
        self._status_lock = threading.Lock()
        self._node = None
        self._spin_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._owns_rclpy = False
        self._fault_rooms = [
            r.strip().lower()
            for r in os.environ.get("MAS_FAULT_ROOMS", "").split(",")
            if r.strip()
        ]
        self._faults_fired: List[str] = []
        # Com MAS_FAULT_PERSISTENT=1 a falha se repete em toda tentativa
        # (usado para verificar se o sistema sai do loop em vez de travar).
        self._fault_persistent = os.environ.get("MAS_FAULT_PERSISTENT", "0") == "1"

        if not self.simulated:
            self._start_ros()
        if self.simulated:
            print("[Ros2Bridge] MODO SIMULADO ativo (sem ROS 2 real).")
            if self._fault_rooms:
                print(f"[Ros2Bridge] Falhas injetadas para: {self._fault_rooms}")

    # -- ciclo de vida ------------------------------------------------------ #
    def _start_ros(self) -> None:
        try:
            import rclpy
            from rclpy.node import Node
            from std_msgs.msg import String
            from geometry_msgs.msg import Twist
        except ImportError as exc:
            print(f"[Ros2Bridge] rclpy indisponível ({exc}). Caindo para modo simulado.")
            self.simulated = True
            return

        try:
            if not rclpy.ok():
                rclpy.init()
                self._owns_rclpy = True  # quem inicializa é quem finaliza

            bridge = self

            class _MasBridgeNode(Node):
                def __init__(self) -> None:
                    super().__init__("mas_cognitive_bridge")
                    self.room_pub = self.create_publisher(String, TOPIC_ROOM, 10)
                    self.cmd_vel_pub = self.create_publisher(Twist, TOPIC_CMD_VEL, 10)
                    self.tts_pub = self.create_publisher(String, TOPIC_TTS, 10)
                    self.create_subscription(String, TOPIC_NAV_STATUS, self._on_status, 10)
                    self.create_subscription(String, TOPIC_NAV_RESULT, self._on_status, 10)
                    self.get_logger().info("Ponte cognitiva MAS conectada ao ROS 2.")

                def _on_status(self, msg) -> None:
                    bridge._ingest_status(msg.data)

            self._node = _MasBridgeNode()
            self._rclpy = rclpy
            self._String = String
            self._Twist = Twist
            self._spin_thread = threading.Thread(target=self._spin, daemon=True)
            self._spin_thread.start()
            print("[Ros2Bridge] Conectado ao ROS 2.")
        except Exception as exc:  # noqa: BLE001 - qualquer falha derruba para simulação
            print(f"[Ros2Bridge] Falha ao iniciar o nó ROS 2 ({exc}). Modo simulado.")
            self.simulated = True
            self._node = None

    def _spin(self) -> None:
        while not self._stop_event.is_set() and self._rclpy.ok():
            node = self._node
            if node is None:
                break
            try:
                self._rclpy.spin_once(node, timeout_sec=0.1)
            except Exception:  # noqa: BLE001 - o spin não pode derrubar o grafo
                time.sleep(0.1)

    def shutdown(self) -> None:
        """Encerra a ponte: para o spin ANTES de destruir o nó (evita corrida)."""
        self._stop_event.set()
        if self._spin_thread is not None and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)
        self._spin_thread = None

        node, self._node = self._node, None
        if node is not None:
            try:
                node.destroy_node()
            except Exception:  # noqa: BLE001
                pass
        if self._owns_rclpy:
            try:
                if self._rclpy.ok():
                    self._rclpy.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._owns_rclpy = False
        self._initialized = False
        Ros2Bridge._instance = None

    # -- estado ------------------------------------------------------------- #
    @staticmethod
    def normalize_status(raw: str) -> str:
        """Converte o texto publicado pelo ROS 2 em um dos status canônicos."""
        text = (raw or "").strip().lower()
        if not text:
            return STATUS_IDLE
        if "success" in text or "succeeded" in text or "arrived" in text:
            return STATUS_SUCCESS
        if "blocked" in text or "canceled" in text or "cancelled" in text or "aborted" in text:
            return STATUS_PATH_BLOCKED
        if "error" in text or "fail" in text or "reject" in text:
            return STATUS_ERROR
        if "running" in text or "navigating" in text or "active" in text:
            return STATUS_RUNNING
        return STATUS_IDLE

    def _ingest_status(self, raw: str) -> None:
        status = self.normalize_status(raw)
        with self._status_lock:
            self._status = status
            self._last_feedback = {"raw": raw, "status": status, "ts": time.time()}
        print(f"[Ros2Bridge] /{TOPIC_NAV_STATUS.lstrip('/')} -> '{raw}' ({status})")

    def set_status(self, status: str, raw: str = "") -> None:
        with self._status_lock:
            self._status = status
            self._last_feedback = {"raw": raw or status, "status": status, "ts": time.time()}

    def get_status(self) -> str:
        with self._status_lock:
            return self._status

    def get_feedback(self) -> Dict[str, Any]:
        with self._status_lock:
            return dict(self._last_feedback)

    def reset_status(self) -> None:
        """Chamado pelo Supervisor antes de despachar uma nova subtarefa."""
        self.set_status(STATUS_RUNNING, "aguardando execução da subtarefa")

    # -- ações -------------------------------------------------------------- #
    def publish_goal(self, goal_key: str) -> None:
        if self.simulated or self._node is None:
            return
        msg = self._String()
        msg.data = goal_key
        self._node.room_pub.publish(msg)

    def publish_twist(self, linear_x: float, angular_z: float, duration: float) -> None:
        if self.simulated or self._node is None:
            time.sleep(min(duration, 0.2))
            return
        msg = self._Twist()
        msg.linear.x = float(linear_x)
        msg.angular.z = float(angular_z)
        deadline = time.time() + duration
        while time.time() < deadline:
            self._node.cmd_vel_pub.publish(msg)
            time.sleep(0.1)
        stop = self._Twist()
        for _ in range(3):  # garante a parada mesmo com perda de pacote
            self._node.cmd_vel_pub.publish(stop)
            time.sleep(0.05)

    def publish_speech(self, text: str) -> None:
        if self.simulated or self._node is None:
            return
        msg = self._String()
        msg.data = text
        self._node.tts_pub.publish(msg)

    def wait_for_navigation(self, timeout: float = NAV_TIMEOUT) -> str:
        """Bloqueia até o Nav2 publicar um status terminal ou estourar o timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.get_status()
            if status in (STATUS_SUCCESS, STATUS_PATH_BLOCKED, STATUS_ERROR):
                return status
            time.sleep(0.2)
        self.set_status(STATUS_ERROR, f"timeout de {timeout:.0f}s aguardando o Nav2")
        return STATUS_ERROR

    # -- simulação ---------------------------------------------------------- #
    def simulate_navigation(self, room: str) -> str:
        """Percurso simulado, com injeção opcional de falhas para testes de resiliência."""
        time.sleep(SIM_NAV_DURATION)
        key = room.lower()
        for fault in self._fault_rooms:
            if fault in key and (self._fault_persistent or fault not in self._faults_fired):
                self._faults_fired.append(fault)  # por padrão, falha só na 1ª tentativa
                self.set_status(STATUS_PATH_BLOCKED, f"[SIM] porta fechada a caminho de {room}")
                return STATUS_PATH_BLOCKED
        self.set_status(STATUS_SUCCESS, f"[SIM] robô chegou em {room}")
        return STATUS_SUCCESS


def get_bridge() -> Ros2Bridge:
    return Ros2Bridge()


# --------------------------------------------------------------------------- #
# Toolkit exposto aos agentes
# --------------------------------------------------------------------------- #
@tool
def tool_navigateTo(room: str) -> str:
    """
    Navega o robô até um cômodo ou ponto do mapa usando o Nav2.
    Traduz o nome do cômodo em coordenadas e aguarda a confirmação real do robô.
    Use para qualquer subtarefa de deslocamento (ex.: "ir até a cozinha").
    Argumento: room - nome do cômodo de destino (ex.: "cozinha", "sala").
    """
    bridge = get_bridge()
    goal_key = resolve_room(room)
    if goal_key is None:
        return (
            f"ERRO: destino '{room}' não existe no mapa. "
            f"Destinos válidos: {available_rooms()}"
        )

    print(f"[Toolkit] tool_navigateTo -> '{room}' (meta Nav2: '{goal_key}')")
    bridge.set_status(STATUS_RUNNING, f"navegando para {goal_key}")

    if bridge.simulated:
        status = bridge.simulate_navigation(goal_key)
    else:
        bridge.publish_goal(goal_key)
        status = bridge.wait_for_navigation()

    feedback = bridge.get_feedback().get("raw", status)
    if status == STATUS_SUCCESS:
        return f"SUCCESS: robô chegou em '{goal_key}'."
    if status == STATUS_PATH_BLOCKED:
        return f"PATH_BLOCKED: caminho até '{goal_key}' bloqueado. Detalhe: {feedback}"
    return f"ERROR: falha ao navegar até '{goal_key}'. Detalhe: {feedback}"


@tool
def tool_reverseRobot(duration_seconds: float = 2.0, speed: float = 0.2) -> str:
    """
    Faz o robô dar ré publicando velocidade negativa em /cmd_vel.
    Use para desvencilhar o robô quando ele estiver preso ou com o caminho bloqueado,
    antes de tentar uma rota alternativa.
    Argumentos: duration_seconds - tempo de ré em segundos; speed - módulo da velocidade (m/s).
    """
    bridge = get_bridge()
    duration = max(0.1, min(float(duration_seconds), 10.0))
    linear = -abs(float(speed))
    print(f"[Toolkit] tool_reverseRobot -> {duration:.1f}s a {linear:.2f} m/s")
    try:
        bridge.publish_twist(linear_x=linear, angular_z=0.0, duration=duration)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: falha ao publicar em {TOPIC_CMD_VEL}: {exc}"
    bridge.set_status(STATUS_SUCCESS, "manobra de ré concluída")
    return f"SUCCESS: robô recuou por {duration:.1f}s a {abs(linear):.2f} m/s."


@tool
def tool_rotateRobot(duration_seconds: float = 1.5, angular_speed: float = 0.5) -> str:
    """
    Gira o robô no próprio eixo publicando velocidade angular em /cmd_vel.
    Use após uma ré para reorientar o robô em direção a uma rota alternativa.
    Argumentos: duration_seconds - tempo de giro; angular_speed - rad/s
    (positivo gira para a esquerda, negativo para a direita).
    """
    bridge = get_bridge()
    duration = max(0.1, min(float(duration_seconds), 10.0))
    print(f"[Toolkit] tool_rotateRobot -> {duration:.1f}s a {angular_speed:.2f} rad/s")
    try:
        bridge.publish_twist(linear_x=0.0, angular_z=float(angular_speed), duration=duration)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: falha ao publicar em {TOPIC_CMD_VEL}: {exc}"
    bridge.set_status(STATUS_SUCCESS, "manobra de giro concluída")
    sentido = "esquerda" if angular_speed >= 0 else "direita"
    return f"SUCCESS: robô girou para a {sentido} por {duration:.1f}s."


@tool
def tool_findPerson(person_name: str) -> str:
    """
    Dispara o módulo de visão computacional para procurar uma pessoa no cômodo atual.
    Argumento: person_name - nome da pessoa procurada.
    """
    bridge = get_bridge()
    print(f"[Toolkit] tool_findPerson -> '{person_name}'")
    if not bridge.simulated:
        try:  # reaproveita o módulo de visão do sistema legado, se disponível
            from robot_tools import find_person  # type: ignore

            result = find_person.invoke({"input_str": json.dumps({"person": person_name})})
            return str(result)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: módulo de visão indisponível ({exc})."
    return f"SUCCESS: [SIM] pessoa '{person_name}' localizada no cômodo atual."


@tool
def tool_speakToUser(text: str) -> str:
    """
    Envia um texto para o módulo de síntese de voz (TTS) do robô falar com o usuário.
    Use para reportar progresso, pedir passagem ou confirmar a conclusão de uma tarefa.
    Argumento: text - frase a ser falada.
    """
    bridge = get_bridge()
    print(f"[ROBÔ FALA] {text}")
    try:
        bridge.publish_speech(text)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: falha ao publicar em {TOPIC_TTS}: {exc}"
    return f"SUCCESS: mensagem falada -> '{text}'"


@tool
def tool_queryKnowledgeBase(query: str) -> str:
    """
    Consulta a base de conhecimento local (RAG/ChromaDB) com as regras da RoboCup@Home
    e informações do ambiente. Use quando precisar de uma regra ou um dado do cenário
    antes de decidir uma ação.
    Argumento: query - pergunta em linguagem natural.
    """
    print(f"[Toolkit] tool_queryKnowledgeBase -> '{query}'")
    try:
        from rag_pipeline import get_context  # type: ignore

        context = get_context(query)
        if context:
            return f"SUCCESS: {context}"
        return "SUCCESS: nenhum trecho relevante encontrado na base de conhecimento."
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: base de conhecimento indisponível ({exc})."


@tool
def tool_getNavigationStatus() -> str:
    """
    Lê o último status publicado pelo ROS 2 no tópico /navigation_status.
    Retorna um entre: IDLE, RUNNING, SUCCESS, PATH_BLOCKED, ERROR.
    """
    bridge = get_bridge()
    status = bridge.get_status()
    feedback = bridge.get_feedback().get("raw", "")
    return f"{status} | detalhe: {feedback}" if feedback else status


# Toolkit completo entregue ao Agente Executor (padrão ReAct)
ROBOT_TOOLKIT = [
    tool_navigateTo,
    tool_reverseRobot,
    tool_rotateRobot,
    tool_findPerson,
    tool_speakToUser,
    tool_queryKnowledgeBase,
    tool_getNavigationStatus,
]

TOOLS_BY_NAME = {t.name: t for t in ROBOT_TOOLKIT}
