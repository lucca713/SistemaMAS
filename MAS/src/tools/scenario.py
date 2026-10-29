"""
Estado do mundo simulado para percepcao e manipulacao.

A navegacao e REAL (Nav2 no Gazebo). Percepcao (achar pessoa/objeto) e
manipulacao (pegar/entregar) sao SIMULADAS contra o ground truth de
Scenarios/baseline_house_1.json, lido pelo ScenarioManager legado do modulo de
PLN. E a mesma estrategia do sistema legado: nao existe modulo de visao nem
braco no simulador, entao a Tabela 3 do projeto aponta essas ferramentas para
modulos que respondem a partir do cenario.

Esta separacao importa para a leitura das metricas: TCR e FRR medem o
RACIOCINIO (decompor, detectar falha, replanejar), nao a acuracia de um
detector de objetos que nao existe.
"""

import os
import sys

# O ScenarioManager legado so depende de json/os/typing, entao importa limpo.
_LEGADO = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "ros2_ws_victor", "robot-agent", "ros2_ws"))
if _LEGADO not in sys.path:
    sys.path.append(_LEGADO)

from scenario_manager import ScenarioManager  # noqa: E402

CENARIO_PADRAO = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "ros2_ws_victor", "robot-agent", "Scenarios", "baseline_house_1.json"))

# Capacidade de carga do robo (mesmo valor usado pelo robot_tools legado).
PESO_MAXIMO_KG = 3.0


class Mundo:
    """Ground truth do cenario + estado de manipulacao do robo."""

    def __init__(self, cenario: str = None, salas_navegaveis=None):
        self.cenario_path = cenario or os.environ.get("MAS_SCENARIO", CENARIO_PADRAO)
        self.sm = ScenarioManager(self.cenario_path)
        # Apenas as salas que tem waypoint no mapa podem ser visitadas.
        self.salas_navegaveis = list(salas_navegaveis or [])
        self.reset()

    def reset(self):
        """Zera o estado de manipulacao (chamado entre execucoes do experimento)."""
        self.sala_atual = "hall"
        self.carregando = None          # objeto na mao, ou None
        self.entregas = []              # [(objeto, local)]
        self.pessoas_encontradas = []   # [(nome, sala)]
        self.objetos_encontrados = []   # [(objeto, sala)]
        self.falas = []                 # mensagens ditas ao usuario
        self.salas_visitadas = ["hall"]  # evita que o plano revisite comodos

    # ------------------------------------------------------------- consultas

    def salas(self):
        """Salas conhecidas, restritas as que tem waypoint no mapa."""
        todas = self.sm.get_all_rooms()
        if not self.salas_navegaveis:
            return todas
        return [s for s in todas if s in self.salas_navegaveis]

    def pessoa_na_sala(self, nome, sala):
        return self.sm.check_person_in_room(nome, sala)

    def objeto_na_sala(self, obj, sala):
        return self.sm.check_object_in_room(obj, sala)

    def peso(self, obj, sala):
        return self.sm.get_object_weight(obj, sala)

    def localizacao_pessoa(self, nome):
        return self.sm.get_person_location(nome)

    def localizacao_objeto(self, obj):
        """Primeira sala navegavel que contem o objeto (ou None)."""
        for s in self.salas():
            if self.objeto_na_sala(obj, s):
                return s
        return None

    def objetos_leves_em(self, sala):
        """Objetos que o robo consegue carregar naquela sala."""
        return [o["type"] for o in self.sm.get_objects_in_room(sala)
                if (o.get("weight_kg") or 999) <= PESO_MAXIMO_KG]

    # ------------------------------------------------- mutacoes de estado

    def chegou_em(self, sala):
        self.sala_atual = sala
        if sala not in self.salas_visitadas:
            self.salas_visitadas.append(sala)

    def pegar(self, obj):
        """Tenta pegar. Devolve (ok, motivo)."""
        if self.carregando:
            return False, f"Ja estou carregando '{self.carregando}'."
        if not self.objeto_na_sala(obj, self.sala_atual):
            return False, f"'{obj}' nao esta em '{self.sala_atual}'."
        p = self.peso(obj, self.sala_atual)
        if p is not None and p > PESO_MAXIMO_KG:
            return False, (f"'{obj}' pesa {p} kg e eu carrego no maximo "
                           f"{PESO_MAXIMO_KG} kg.")
        self.carregando = obj
        return True, f"'{obj}' pego ({p} kg)."

    def entregar(self, obj, local):
        """Tenta entregar. Devolve (ok, motivo)."""
        if self.carregando is None:
            return False, "Nao estou carregando nada."
        if obj and self.carregando.lower() != obj.lower():
            return False, f"Estou carregando '{self.carregando}', nao '{obj}'."
        entregue = self.carregando
        self.carregando = None
        self.entregas.append((entregue, local or self.sala_atual))
        return True, f"'{entregue}' entregue em '{local or self.sala_atual}'."

    def registrar_pessoa(self, nome, sala):
        self.pessoas_encontradas.append((nome, sala))

    def registrar_objeto(self, obj, sala):
        self.objetos_encontrados.append((obj, sala))

    def registrar_fala(self, msg):
        self.falas.append(msg)


# --------------------------------------------------------------- singleton

_mundo = None


def get_mundo(salas_navegaveis=None) -> Mundo:
    global _mundo
    if _mundo is None:
        _mundo = Mundo(salas_navegaveis=salas_navegaveis)
    return _mundo


def reset_mundo():
    """Reinicia o mundo entre execucoes, mantendo o cenario carregado."""
    if _mundo is not None:
        _mundo.reset()
