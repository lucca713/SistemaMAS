"""
Ponte ROS 2 do modulo de raciocinio.

Um unico no persistente, criado no boot e girado numa thread de fundo.
Isso resolve dois problemas do codigo anterior:

1. Race condition: o listener de /nav_result era criado DEPOIS de publicar a
   meta em /room. Se o Nav2 respondesse rapido, a mensagem se perdia e o
   agente comia 60s de timeout. Aqui a inscricao existe desde o boot.

2. Mentira: o resultado do Nav2 era aceito cegamente. Aqui, alem de ouvir o
   /nav_result, a gente confere a posicao real do robo via TF (map -> base_link)
   e compara com a coordenada da meta. Se o Nav2 disser "sucesso" mas o robo
   estiver longe, o relatorio diz que NAO chegou.
"""

import json
import math
import re
import os
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.parameter import Parameter
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup

from std_msgs.msg import String
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Point
from builtin_interfaces.msg import Duration
from nav2_msgs.action import BackUp, NavigateToPose, Spin
from geometry_msgs.msg import PoseStamped

from tf2_ros import Buffer, TransformListener

# Raiz do repo: MAS/src/tools/ros_bridge.py -> sobe 3 niveis
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GOALS_FILE = os.environ.get(
    "MAS_GOALS_FILE",
    os.path.join(_REPO, "ros2_ws_vinicius", "src", "robot_bringup", "config", "goalsTest.json"),
)

# Distancia (m) ate a meta abaixo da qual consideramos que o robo realmente chegou.
# O goal_checker do Nav2 usa xy_goal_tolerance: 0.25; damos folga para ruido de TF.
ARRIVAL_TOLERANCE = float(os.environ.get("MAS_ARRIVAL_TOLERANCE", "0.65"))

# Se o Nav2 falhar e o robo tiver andado menos que isso, ele esta travado.
STUCK_DISTANCE = 0.15

# Onde a origem do frame `map` cai no mundo do Gazebo.
# O mapa salvo do Cenario1 foi levantado a partir do spawn do robo, que o
# main.sdf define em (-3.9, -5.8). Logo map(0,0) == mundo(-3.9,-5.8), e as
# coordenadas do Nav2 NAO sao as do Gazebo -- comparar as duas direto daria um
# erro fantasma de 7 m na verificacao.
MAP_ORIGEM_MUNDO = (float(os.environ.get("MAS_MAP_ORIGIN_X", "-3.9")),
                    float(os.environ.get("MAS_MAP_ORIGIN_Y", "-5.8")))

# --- Injecao de falha, para medir a FRR (secao 8.3 do projeto) -------------
# MAS_FAULT_ROOMS="kitchen,bedroom" faz a navegacao para essas salas falhar.
# Por padrao a falha ocorre so na PRIMEIRA tentativa de cada sala, simulando
# "porta bloqueada" que o replanejamento consegue contornar. Com
# MAS_FAULT_PERSISTENT=1 a falha se repete sempre (serve para checar se o
# sistema desiste honestamente em vez de girar para sempre).
def _salas_com_falha():
    return [r.strip().lower()
            for r in os.environ.get("MAS_FAULT_ROOMS", "").split(",") if r.strip()]


def load_goals() -> dict:
    """Carrega o JSON de metas usado pelo navigate_to_goal.py."""
    with open(GOALS_FILE, "r") as f:
        return json.load(f)


class RosBridge(Node):
    def __init__(self):
        super().__init__(
            "mas_ros_bridge",
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        cb = ReentrantCallbackGroup()

        self.goals = load_goals()

        # Contrato legado: a meta de navegacao sai no topico /room.
        self.room_pub = self.create_publisher(String, "room", 10)

        # Inscricoes criadas JA no boot (sem race).
        self.create_subscription(String, "nav_result", self._on_nav_result, 10, callback_group=cb)
        self.create_subscription(Odometry, "odom", self._on_odom, 10, callback_group=cb)

        # Comportamentos do Nav2. Publicar Twist cru em /cmd_vel nao funciona
        # com o Nav2 no ar: o controller_server publica a 20 Hz no mesmo topico
        # e sobrescreve o comando manual. O behavior_server e o dono legitimo.
        self._backup_client = ActionClient(self, BackUp, "backup", callback_group=cb)
        self._spin_client = ActionClient(self, Spin, "spin", callback_group=cb)
        # Cliente direto do Nav2, usado para SONDAR coordenadas sem precisar
        # reescrever o JSON de metas e reiniciar o no de navegacao.
        self._nav_client = ActionClient(self, NavigateToPose, "navigate_to_pose",
                                        callback_group=cb)

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self._nav_event = threading.Event()
        self._nav_msg = None
        self._alvo_esperado = None
        self._odom = None
        self._cancel_pub = self.create_publisher(String, "nav_cancel", 10)

        self._tts_pub = self.create_publisher(String, "tts", 10)
        self._falhas_disparadas = set()

        self.get_logger().info(f"Ponte MAS pronta. Metas de {GOALS_FILE}: {list(self.goals)}")

    # ------------------------------------------------------------------ callbacks

    def _on_nav_result(self, msg: String):
        """
        Aceita so o resultado da meta que esta sendo esperada.

        Sem este filtro, um /nav_result atrasado de uma navegacao anterior
        (tipicamente apos timeout) era lido como resposta da navegacao atual --
        foi o que fez quatro destinos "falharem" em 0.0s em sequencia.
        """
        dado = msg.data or ""
        partes = dado.split(":")
        alvo_msg = partes[1].strip() if len(partes) > 1 else None
        if (self._alvo_esperado and alvo_msg
                and alvo_msg.lower() != self._alvo_esperado.lower()):
            self.get_logger().warn(
                f"Descartando /nav_result de outra meta: '{dado}' "
                f"(esperando '{self._alvo_esperado}')")
            return
        self._nav_msg = dado
        self._nav_event.set()

    def _on_odom(self, msg: Odometry):
        p = msg.pose.pose.position
        self._odom = (p.x, p.y)

    # ------------------------------------------------------------------ leitura de estado

    def pose_real(self):
        """
        Pose VERDADEIRA do robo, lida direto do Gazebo.

        Por que existe: o TF `map->base_link` e o que o robo ACREDITA, e ele
        pode mentir. Nesta sessao o robo tombou sobre uma mesa, as rodas
        patinaram, a odometria acumulou ~30 m de erro e o TF passou a reportar
        (-0.65, 0.61) enquanto o robo estava de fato em (-8.08, -7.12).

        Divisao de papeis que isto permite:
          * o AGENTE decide usando `map_pose()` (o que ele sabe, como no robo real);
          * o VERIFICADOR do experimento confere com `pose_real()` (o que aconteceu);
          * a diferenca entre as duas e o erro de localizacao, que vira metrica.
        """
        import subprocess
        try:
            out = subprocess.run(
                ["ign", "topic", "-e", "-t", "/world/empty/pose/info", "-n", "1"],
                capture_output=True, text=True, timeout=12).stdout
        except Exception:
            return None
        # Procura o bloco do modelo "Robot" e le a primeira position depois dele
        i = out.find('name: "Robot"')
        if i < 0:
            return None
        bloco = out[i:i + 400]
        j = bloco.find("position")
        if j < 0:
            return None
        xs = re.findall(r"([xyz]):\s*(-?[\d.eE+-]+)", bloco[j:j + 220])
        d = {}
        for k, v in xs:
            if k not in d:
                d[k] = float(v)
        if "x" in d and "y" in d:
            return (d["x"], d["y"], d.get("z", 0.0))
        return None

    def pose_real_map(self):
        """Pose verdadeira do Gazebo convertida para o frame `map` do Nav2."""
        r = self.pose_real()
        if r is None:
            return None
        return (r[0] - MAP_ORIGEM_MUNDO[0], r[1] - MAP_ORIGEM_MUNDO[1], r[2])

    def erro_localizacao(self):
        """Distancia entre o que o robo acha que esta (TF) e onde esta (verdade)."""
        tf, real = self.map_pose(), self.pose_real_map()
        if tf is None or real is None:
            return None
        return math.hypot(tf[0] - real[0], tf[1] - real[1])

    def distancia_real_ate(self, nome):
        """Distancia VERDADEIRA ate uma meta, no frame do mapa."""
        g = self.goals.get(nome)
        r = self.pose_real_map()
        if not g or r is None:
            return None
        return math.hypot(r[0] - g["x"], r[1] - g["y"])

    def tombado(self, limite_z=0.55):
        """True se o robo esta alto demais: subiu em obstaculo ou tombou."""
        r = self.pose_real()
        return bool(r and r[2] > limite_z)

    def map_pose(self):
        """Posicao real do robo no frame do mapa, ou None se o TF nao estiver pronto."""
        try:
            t = self._tf_buffer.lookup_transform("map", "base_link", rclpy.time.Time())
            return (t.transform.translation.x, t.transform.translation.y)
        except Exception:
            return None

    def odom_pose(self):
        return self._odom

    def _distance_to_goal(self, goal_name):
        """Distancia real ate a meta, ou None se nao der para medir."""
        pose = self.map_pose()
        if pose is None or goal_name not in self.goals:
            return None
        g = self.goals[goal_name]
        return math.hypot(pose[0] - g["x"], pose[1] - g["y"])

    def sala_mais_proxima(self, tol: float = 2.0):
        """Comodo cujo waypoint esta mais perto da pose atual, ou None."""
        pose = self.map_pose()
        if pose is None:
            return None
        melhor, menor = None, float("inf")
        for nome, g in self.goals.items():
            d = math.hypot(pose[0] - g["x"], pose[1] - g["y"])
            if d < menor:
                melhor, menor = nome, d
        return melhor if menor <= tol else None

    def resolve_goal(self, name: str):
        """Casa o nome pedido com uma meta do JSON (case-insensitive)."""
        if not name:
            return None
        alvo = name.strip().lower()
        for real in self.goals:
            if real.lower() == alvo:
                return real
        for real in self.goals:  # tolera 'o bloco', 'bloco azul'
            if real.lower() in alvo or alvo in real.lower():
                return real
        return None

    # ------------------------------------------------------------------ falhas injetadas

    def _deve_falhar(self, alvo: str) -> bool:
        """True se esta navegacao deve receber uma falha injetada."""
        alvo_l = alvo.lower()
        if alvo_l not in _salas_com_falha():
            return False
        persistente = os.environ.get("MAS_FAULT_PERSISTENT", "0") == "1"
        if persistente:
            return True
        if alvo_l in self._falhas_disparadas:
            return False
        self._falhas_disparadas.add(alvo_l)
        return True

    def reset_mundo_gazebo(self, espera: float = 4.0) -> dict:
        """
        Reseta o mundo do Gazebo: modelos voltam a pose inicial e o tempo zera.

        Serve para dar a cada execucao do experimento a MESMA condicao inicial.
        O que motivou isto: a odometria do DiffDrive integra rotacao de roda e
        nunca zera sozinha; depois que o robo tombou e as rodas patinaram, ela
        carregou 13 m de erro permanente e derrubou a localizacao. Sem reset,
        cada execucao herdaria o estado degradado da anterior.
        """
        import subprocess
        try:
            r = subprocess.run(
                ["ign", "service", "-s", "/world/empty/control",
                 "--reqtype", "ignition.msgs.WorldControl",
                 "--reptype", "ignition.msgs.Boolean",
                 "--timeout", "5000",
                 "--req", "reset: {all: true}, pause: false"],
                capture_output=True, text=True, timeout=20)
            ok = "true" in (r.stdout or "").lower()
        except Exception as e:
            return {"ok": False, "detail": f"reset falhou: {e}"}
        time.sleep(espera)
        self._falhas_disparadas = set()
        self._nav_msg = None
        self._alvo_esperado = None
        self._nav_event.clear()
        return {"ok": ok, "detail": "mundo resetado" if ok else "servico nao confirmou"}

    def limpar_costmaps(self) -> None:
        """Esquece obstaculos antigos do Nav2 depois de um reset do mundo."""
        import subprocess
        for srv in ("/global_costmap/clear_entirely_global_costmap",
                    "/local_costmap/clear_entirely_local_costmap"):
            try:
                subprocess.run(["ros2", "service", "call", srv,
                                "nav2_msgs/srv/ClearEntireCostmap", "{}"],
                               capture_output=True, text=True, timeout=20)
            except Exception:
                pass

    def odometria(self):
        """Leitura crua da odometria acumulada (para checar se o reset zerou)."""
        return self._odom

    def relocalizar(self, espera: float = 6.0) -> dict:
        """
        Reancora o AMCL na pose verdadeira do robo.

        Usado para INICIALIZAR a localizacao, nao para corrigi-la durante a
        missao: um robo real recebe sua pose inicial (ou faz localizacao
        global) ao ser ligado. Durante a execucao o agente so usa o TF.
        """
        import subprocess
        r = self.pose_real_map()
        if r is None:
            return {"ok": False, "detail": "sem pose verdadeira do Gazebo"}
        msg = ("{header: {frame_id: 'map'}, pose: {pose: {position: "
               f"{{x: {r[0]:.4f}, y: {r[1]:.4f}, z: 0.0}}, orientation: {{w: 1.0}}}}, "
               "covariance: [0.25,0,0,0,0,0, 0,0.25,0,0,0,0, 0,0,0,0,0,0, "
               "0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.07]}}")
        try:
            # '-t 6 -r 1' em vez de '--once': o publicador de uma mensagem so
            # morre antes do discovery do DDS completar e o AMCL nunca recebe.
            subprocess.run(["ros2", "topic", "pub", "-t", "6", "-r", "1", "/initialpose",
                            "geometry_msgs/msg/PoseWithCovarianceStamped", msg],
                           capture_output=True, text=True, timeout=45)
        except Exception as e:
            return {"ok": False, "detail": f"falha ao publicar /initialpose: {e}"}
        time.sleep(espera)
        err = self.erro_localizacao()
        return {"ok": err is not None and err < 1.0,
                "detail": f"relocalizado em map({r[0]:.2f}, {r[1]:.2f}); "
                          f"erro agora {err:.2f} m" if err is not None else "sem erro medido"}

    def reset_falhas(self):
        """Rearma as falhas injetadas (chamado entre execucoes do experimento)."""
        self._falhas_disparadas = set()

    def falar(self, texto: str) -> dict:
        msg = String()
        msg.data = texto
        self._tts_pub.publish(msg)
        print(f"[ROBO FALA] {texto}")
        return {"ok": True, "detail": f"Mensagem falada: '{texto}'"}

    # ------------------------------------------------------------------ acoes

    def navigate(self, goal_name: str, timeout: float = 120.0) -> dict:
        """
        Manda o robo para uma meta e relata o que REALMENTE aconteceu.

        Retorna {"ok", "detail", "distance", "stuck"}.
        """
        alvo = self.resolve_goal(goal_name)
        if alvo is None:
            return {
                "ok": False,
                "stuck": False,
                "detail": (
                    f"Destino '{goal_name}' nao existe. "
                    f"Destinos validos: {', '.join(self.goals)}"
                ),
            }

        if self._deve_falhar(alvo):
            dist = self._distance_to_goal(alvo)
            return {
                "ok": False,
                "stuck": True,
                "injected": True,
                "distance": dist,
                "detail": (
                    f"[FALHA INJETADA] Caminho para '{alvo}' bloqueado (porta fechada). "
                    "O robo nao saiu do lugar e precisa recuar antes de tentar outra rota."
                ),
            }

        # Se ninguem escuta /room, o modulo de navegacao nao esta no ar.
        prazo = time.time() + 5.0
        while self.room_pub.get_subscription_count() == 0 and time.time() < prazo:
            time.sleep(0.1)
        if self.room_pub.get_subscription_count() == 0:
            return {
                "ok": False,
                "stuck": False,
                "detail": "Ninguem esta inscrito em /room: o navigate_to_goal.py nao esta rodando.",
            }

        partida = self.map_pose() or self.odom_pose()
        self._nav_msg = None
        self._alvo_esperado = alvo
        self._nav_event.clear()

        msg = String()
        msg.data = alvo
        self.room_pub.publish(msg)
        self.get_logger().info(f"Meta despachada em /room: '{alvo}'")

        recebeu = self._nav_event.wait(timeout=timeout)
        dist = self._distance_to_goal(alvo)
        chegada = self.map_pose() or self.odom_pose()

        andou = None
        if partida and chegada:
            andou = math.hypot(chegada[0] - partida[0], chegada[1] - partida[1])

        if not recebeu:
            # Cancela a meta pendente: deixa-la ativa fazia o Nav2 abortar
            # todas as metas seguintes.
            c = String()
            c.data = alvo
            self._cancel_pub.publish(c)
            self.get_logger().warn(f"Timeout: cancelamento de '{alvo}' solicitado.")
            time.sleep(1.0)
            self._alvo_esperado = None
            return {
                "ok": False,
                "stuck": andou is not None and andou < STUCK_DISTANCE,
                "distance": dist,
                "detail": (
                    f"Nav2 nao respondeu em {timeout:.0f}s indo para '{alvo}'. "
                    f"Distancia ate a meta: {dist:.2f}m. " if dist is not None else
                    f"Nav2 nao respondeu em {timeout:.0f}s indo para '{alvo}'. "
                ) + (f"Robo andou {andou:.2f}m." if andou is not None else ""),
            }

        bruto = self._nav_msg or ""
        self._alvo_esperado = None
        nav_ok = bruto.startswith("success")

        # Verificacao fisica independente: o Nav2 pode mentir, o TF nao.
        if dist is not None:
            chegou_de_fato = dist <= ARRIVAL_TOLERANCE
            if nav_ok and not chegou_de_fato:
                return {
                    "ok": False,
                    "stuck": andou is not None and andou < STUCK_DISTANCE,
                    "distance": dist,
                    "detail": (
                        f"Nav2 reportou '{bruto}', mas o robo esta a {dist:.2f}m de '{alvo}' "
                        f"(tolerancia {ARRIVAL_TOLERANCE}m). NAO chegou."
                    ),
                }
            if not nav_ok and chegou_de_fato:
                return {
                    "ok": True,
                    "stuck": False,
                    "distance": dist,
                    "detail": f"Nav2 reportou '{bruto}', mas o robo esta a {dist:.2f}m de '{alvo}'. Chegou.",
                }

        sufixo = f" Distancia ate a meta: {dist:.2f}m." if dist is not None else ""
        if nav_ok:
            return {"ok": True, "stuck": False, "distance": dist,
                    "detail": f"Chegou em '{alvo}'.{sufixo}"}

        travado = andou is not None and andou < STUCK_DISTANCE
        return {
            "ok": False,
            "stuck": travado,
            "distance": dist,
            "detail": (
                f"Falha ao navegar para '{alvo}': Nav2 retornou '{bruto}'.{sufixo}"
                + (f" O robo andou so {andou:.2f}m: esta TRAVADO/ENCOSTADO em obstaculo."
                   if travado else "")
            ),
        }

    def navigate_xy(self, x: float, y: float, timeout: float = 90.0) -> dict:
        """
        Manda o robo para uma coordenada crua via action do Nav2.

        Serve para sondar alcancabilidade: o caminho normal (/room -> JSON)
        exigiria reiniciar o no de navegacao a cada candidato testado.
        """
        if not self._nav_client.wait_for_server(timeout_sec=5.0):
            return {"ok": False, "detail": "navigate_to_pose indisponivel", "dist": None}

        g = NavigateToPose.Goal()
        g.pose = PoseStamped()
        g.pose.header.frame_id = "map"
        g.pose.header.stamp.sec = 0
        g.pose.header.stamp.nanosec = 0
        g.pose.pose.position.x = float(x)
        g.pose.pose.position.y = float(y)
        g.pose.pose.orientation.w = 1.0

        partida = self.map_pose()
        fut = self._nav_client.send_goal_async(g)
        prazo = time.time() + timeout
        while not fut.done() and time.time() < prazo:
            time.sleep(0.05)
        if not fut.done():
            return {"ok": False, "detail": "meta nao aceita a tempo", "dist": None}
        h = fut.result()
        if not h.accepted:
            return {"ok": False, "detail": "meta REJEITADA pelo Nav2", "dist": None}

        rf = h.get_result_async()
        while not rf.done() and time.time() < prazo:
            time.sleep(0.1)
        if not rf.done():
            h.cancel_goal_async()
            time.sleep(1.0)
            return {"ok": False, "detail": f"timeout de {timeout:.0f}s", "dist": None}

        st = rf.result().status
        pose = self.map_pose()
        d = math.hypot(pose[0] - x, pose[1] - y) if pose else None
        andou = (math.hypot(pose[0] - partida[0], pose[1] - partida[1])
                 if pose and partida else None)
        ok = (st == 4) or (d is not None and d <= 0.8)
        return {"ok": ok, "dist": d, "andou": andou,
                "detail": (f"status={st} dist={d:.2f}m" if d is not None else f"status={st}")
                          + (f" andou={andou:.2f}m" if andou is not None else "")}

    def _run_behavior(self, client, goal, nome: str, timeout: float) -> dict:
        """Dispara um behavior do Nav2 e mede o deslocamento real via odometria."""
        if not client.wait_for_server(timeout_sec=5.0):
            return {"ok": False, "detail": f"behavior_server do Nav2 indisponivel para '{nome}'."}

        antes = self.odom_pose()
        fut = client.send_goal_async(goal)

        prazo = time.time() + timeout
        while not fut.done() and time.time() < prazo:
            time.sleep(0.05)
        if not fut.done():
            return {"ok": False, "detail": f"'{nome}' nao foi aceito a tempo pelo Nav2."}

        handle = fut.result()
        if not handle.accepted:
            return {"ok": False, "detail": f"Nav2 rejeitou o comando '{nome}'."}

        res_fut = handle.get_result_async()
        while not res_fut.done() and time.time() < prazo:
            time.sleep(0.05)
        if not res_fut.done():
            return {"ok": False, "detail": f"'{nome}' estourou o tempo de {timeout:.0f}s."}

        status = res_fut.result().status
        depois = self.odom_pose()
        andou = None
        if antes and depois:
            andou = math.hypot(depois[0] - antes[0], depois[1] - antes[1])

        if status == 4:  # SUCCEEDED
            extra = f" Deslocou {andou:.2f}m." if andou is not None else ""
            return {"ok": True, "detail": f"'{nome}' concluido.{extra}"}

        extra = f" Deslocou apenas {andou:.2f}m." if andou is not None else ""
        return {"ok": False, "detail": f"'{nome}' falhou (status {status}).{extra}"}

    def backup(self, distance: float = 0.5, speed: float = 0.15) -> dict:
        goal = BackUp.Goal()
        goal.target = Point(x=abs(float(distance)), y=0.0, z=0.0)
        goal.speed = float(speed)
        goal.time_allowance = Duration(sec=20, nanosec=0)
        return self._run_behavior(self._backup_client, goal, f"dar re {distance:.2f}m", 30.0)

    def spin(self, angle_rad: float) -> dict:
        goal = Spin.Goal()
        goal.target_yaw = float(angle_rad)
        goal.time_allowance = Duration(sec=20, nanosec=0)
        graus = math.degrees(angle_rad)
        return self._run_behavior(self._spin_client, goal, f"girar {graus:.0f} graus", 30.0)


# ------------------------------------------------------- ponte simulada (N grande)

class PonteSimulada:
    """
    Mesma interface da RosBridge, sem ROS. Serve para rodar muitas repeticoes
    rapido e obter TCR/FRR com N estatisticamente util.

    IMPORTANTE para a leitura dos resultados: aqui NAO existe verificacao por
    TF -- a chegada e assumida. O raciocinio (decompor, detectar falha,
    replanejar) e exercitado de verdade; a navegacao fisica, nao. Todo
    resultado produzido neste modo deve vir rotulado como 'sim'.
    """

    def __init__(self):
        self.goals = load_goals()
        self._falhas_disparadas = set()
        self._sala = "hall"
        self.atraso = float(os.environ.get("MAS_SIM_NAV_DELAY", "0.05"))

    # --- mesma API da RosBridge ---
    def resolve_goal(self, name):
        if not name:
            return None
        alvo = name.strip().lower()
        for real in self.goals:
            if real.lower() == alvo:
                return real
        for real in self.goals:
            if real.lower() in alvo or alvo in real.lower():
                return real
        return None

    def pose_real(self):
        """
        Pose VERDADEIRA do robo, lida direto do Gazebo.

        Por que existe: o TF `map->base_link` e o que o robo ACREDITA, e ele
        pode mentir. Nesta sessao o robo tombou sobre uma mesa, as rodas
        patinaram, a odometria acumulou ~30 m de erro e o TF passou a reportar
        (-0.65, 0.61) enquanto o robo estava de fato em (-8.08, -7.12).

        Divisao de papeis que isto permite:
          * o AGENTE decide usando `map_pose()` (o que ele sabe, como no robo real);
          * o VERIFICADOR do experimento confere com `pose_real()` (o que aconteceu);
          * a diferenca entre as duas e o erro de localizacao, que vira metrica.
        """
        import subprocess
        try:
            out = subprocess.run(
                ["ign", "topic", "-e", "-t", "/world/empty/pose/info", "-n", "1"],
                capture_output=True, text=True, timeout=12).stdout
        except Exception:
            return None
        # Procura o bloco do modelo "Robot" e le a primeira position depois dele
        i = out.find('name: "Robot"')
        if i < 0:
            return None
        bloco = out[i:i + 400]
        j = bloco.find("position")
        if j < 0:
            return None
        xs = re.findall(r"([xyz]):\s*(-?[\d.eE+-]+)", bloco[j:j + 220])
        d = {}
        for k, v in xs:
            if k not in d:
                d[k] = float(v)
        if "x" in d and "y" in d:
            return (d["x"], d["y"], d.get("z", 0.0))
        return None

    def pose_real_map(self):
        """Pose verdadeira do Gazebo convertida para o frame `map` do Nav2."""
        r = self.pose_real()
        if r is None:
            return None
        return (r[0] - MAP_ORIGEM_MUNDO[0], r[1] - MAP_ORIGEM_MUNDO[1], r[2])

    def erro_localizacao(self):
        """Distancia entre o que o robo acha que esta (TF) e onde esta (verdade)."""
        tf, real = self.map_pose(), self.pose_real_map()
        if tf is None or real is None:
            return None
        return math.hypot(tf[0] - real[0], tf[1] - real[1])

    def distancia_real_ate(self, nome):
        """Distancia VERDADEIRA ate uma meta, no frame do mapa."""
        g = self.goals.get(nome)
        r = self.pose_real_map()
        if not g or r is None:
            return None
        return math.hypot(r[0] - g["x"], r[1] - g["y"])

    def tombado(self, limite_z=0.55):
        """True se o robo esta alto demais: subiu em obstaculo ou tombou."""
        r = self.pose_real()
        return bool(r and r[2] > limite_z)

    def map_pose(self):
        g = self.goals.get(self._sala)
        return (g["x"], g["y"]) if g else (0.0, 0.0)

    def odom_pose(self):
        return self.map_pose()

    def _distance_to_goal(self, nome):
        p, g = self.map_pose(), self.goals.get(nome)
        return math.hypot(p[0] - g["x"], p[1] - g["y"]) if g else None

    def sala_mais_proxima(self, tol=2.0):
        return self._sala

    def _deve_falhar(self, alvo):
        alvo_l = alvo.lower()
        if alvo_l not in _salas_com_falha():
            return False
        if os.environ.get("MAS_FAULT_PERSISTENT", "0") == "1":
            return True
        if alvo_l in self._falhas_disparadas:
            return False
        self._falhas_disparadas.add(alvo_l)
        return True

    def reset_mundo_gazebo(self, espera: float = 4.0) -> dict:
        """
        Reseta o mundo do Gazebo: modelos voltam a pose inicial e o tempo zera.

        Serve para dar a cada execucao do experimento a MESMA condicao inicial.
        O que motivou isto: a odometria do DiffDrive integra rotacao de roda e
        nunca zera sozinha; depois que o robo tombou e as rodas patinaram, ela
        carregou 13 m de erro permanente e derrubou a localizacao. Sem reset,
        cada execucao herdaria o estado degradado da anterior.
        """
        import subprocess
        try:
            r = subprocess.run(
                ["ign", "service", "-s", "/world/empty/control",
                 "--reqtype", "ignition.msgs.WorldControl",
                 "--reptype", "ignition.msgs.Boolean",
                 "--timeout", "5000",
                 "--req", "reset: {all: true}, pause: false"],
                capture_output=True, text=True, timeout=20)
            ok = "true" in (r.stdout or "").lower()
        except Exception as e:
            return {"ok": False, "detail": f"reset falhou: {e}"}
        time.sleep(espera)
        self._falhas_disparadas = set()
        self._nav_msg = None
        self._alvo_esperado = None
        self._nav_event.clear()
        return {"ok": ok, "detail": "mundo resetado" if ok else "servico nao confirmou"}

    def limpar_costmaps(self) -> None:
        """Esquece obstaculos antigos do Nav2 depois de um reset do mundo."""
        import subprocess
        for srv in ("/global_costmap/clear_entirely_global_costmap",
                    "/local_costmap/clear_entirely_local_costmap"):
            try:
                subprocess.run(["ros2", "service", "call", srv,
                                "nav2_msgs/srv/ClearEntireCostmap", "{}"],
                               capture_output=True, text=True, timeout=20)
            except Exception:
                pass

    def odometria(self):
        """Leitura crua da odometria acumulada (para checar se o reset zerou)."""
        return self._odom

    def relocalizar(self, espera: float = 6.0) -> dict:
        """
        Reancora o AMCL na pose verdadeira do robo.

        Usado para INICIALIZAR a localizacao, nao para corrigi-la durante a
        missao: um robo real recebe sua pose inicial (ou faz localizacao
        global) ao ser ligado. Durante a execucao o agente so usa o TF.
        """
        import subprocess
        r = self.pose_real_map()
        if r is None:
            return {"ok": False, "detail": "sem pose verdadeira do Gazebo"}
        msg = ("{header: {frame_id: 'map'}, pose: {pose: {position: "
               f"{{x: {r[0]:.4f}, y: {r[1]:.4f}, z: 0.0}}, orientation: {{w: 1.0}}}}, "
               "covariance: [0.25,0,0,0,0,0, 0,0.25,0,0,0,0, 0,0,0,0,0,0, "
               "0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.07]}}")
        try:
            # '-t 6 -r 1' em vez de '--once': o publicador de uma mensagem so
            # morre antes do discovery do DDS completar e o AMCL nunca recebe.
            subprocess.run(["ros2", "topic", "pub", "-t", "6", "-r", "1", "/initialpose",
                            "geometry_msgs/msg/PoseWithCovarianceStamped", msg],
                           capture_output=True, text=True, timeout=45)
        except Exception as e:
            return {"ok": False, "detail": f"falha ao publicar /initialpose: {e}"}
        time.sleep(espera)
        err = self.erro_localizacao()
        return {"ok": err is not None and err < 1.0,
                "detail": f"relocalizado em map({r[0]:.2f}, {r[1]:.2f}); "
                          f"erro agora {err:.2f} m" if err is not None else "sem erro medido"}

    def reset_falhas(self):
        self._falhas_disparadas = set()

    def falar(self, texto):
        print(f"[ROBO FALA] {texto}")
        return {"ok": True, "detail": f"Mensagem falada: '{texto}'"}

    def navigate(self, goal_name, timeout=120.0):
        alvo = self.resolve_goal(goal_name)
        if alvo is None:
            return {"ok": False, "stuck": False,
                    "detail": (f"Destino '{goal_name}' nao existe. "
                               f"Destinos validos: {', '.join(self.goals)}")}
        if self._deve_falhar(alvo):
            return {"ok": False, "stuck": True, "injected": True,
                    "detail": (f"[FALHA INJETADA] Caminho para '{alvo}' bloqueado "
                               "(porta fechada). O robo nao saiu do lugar e precisa "
                               "recuar antes de tentar outra rota.")}
        time.sleep(self.atraso)
        self._sala = alvo
        return {"ok": True, "stuck": False, "distance": 0.0,
                "detail": f"[SIM] Chegou em '{alvo}'."}

    def backup(self, distance=0.5, speed=0.15):
        time.sleep(self.atraso)
        return {"ok": True, "detail": f"[SIM] 'dar re' concluido. Deslocou {distance:.2f}m."}

    def spin(self, angle_rad):
        time.sleep(self.atraso)
        return {"ok": True, "detail": f"[SIM] 'girar' concluido ({math.degrees(angle_rad):.0f} graus)."}


# ---------------------------------------------------------------------- singleton

_bridge = None
_executor = None
_thread = None


def modo_simulado() -> bool:
    return os.environ.get("MAS_SIM_NAV", "0") == "1"


def get_bridge():
    """Cria (uma vez) a ponte e a gira numa thread de fundo.

    Com MAS_SIM_NAV=1 devolve a PonteSimulada e nao toca no ROS.
    """
    global _bridge, _executor, _thread
    if _bridge is not None:
        return _bridge

    if modo_simulado():
        _bridge = PonteSimulada()
        print("[Ponte] MODO SIMULADO: navegacao nao verificada por TF.")
        return _bridge

    if not rclpy.ok():
        rclpy.init()

    _bridge = RosBridge()
    _executor = MultiThreadedExecutor()
    _executor.add_node(_bridge)
    _thread = threading.Thread(target=_executor.spin, daemon=True)
    _thread.start()

    time.sleep(1.5)  # deixa o discovery do DDS e o TF assentarem
    return _bridge


def shutdown_bridge():
    """Encerra na ordem certa: tira o no do executor, para o spin, so entao destroi."""
    global _bridge, _executor, _thread
    try:
        if _executor is not None and _bridge is not None:
            _executor.remove_node(_bridge)
        if _executor is not None:
            _executor.shutdown(timeout_sec=2.0)
        if _thread is not None and _thread.is_alive():
            _thread.join(timeout=2.0)
        if _bridge is not None:
            _bridge.destroy_node()
    except Exception:
        pass  # encerramento nao pode derrubar a coleta de metricas
    finally:
        _bridge = None
        _executor = None
        _thread = None
        if rclpy.ok():
            rclpy.shutdown()
