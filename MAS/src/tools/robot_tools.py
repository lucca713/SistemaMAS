"""
Toolkit invocavel pelo Agente de Execucao (Tabela 3 do projeto).

Dois principios:

1. Nenhuma tool diz "deu certo" sem ter conferido. Navegacao e verificada por
   TF; manipulacao e verificada contra o ground truth do cenario.

2. As tools sao PRIMITIVAS, nao scripts. A percepcao e por comodo
   (`procurar_pessoa_na_sala`), nunca uma busca multi-comodo embutida. A secao
   7.2 do projeto critica justamente o `find_person` legado, que carregava
   "toda a logica de negocios (buscar comodos, navegar, procurar, repetir)".
   Aqui a busca em varios comodos tem que EMERGIR do plano do Planejador --
   e isso que a arquitetura proposta precisa demonstrar.
"""

import math

from langchain_core.tools import tool

from src.tools.ros_bridge import get_bridge, load_goals
from src.tools.scenario import PESO_MAXIMO_KG, get_mundo


def destinos_validos() -> list:
    """Destinos lidos do mesmo JSON que o navigate_to_goal.py usa."""
    try:
        return list(load_goals().keys())
    except Exception:
        return []


def _mundo():
    return get_mundo(salas_navegaveis=destinos_validos())


def _r(ok: bool, msg: str) -> str:
    return ("SUCESSO: " if ok else "FALHA: ") + msg


# ----------------------------------------------------------------- navegacao

@tool
def navegar_para(destino: str) -> str:
    """Leva o robo ate um comodo do mapa usando o Nav2 e aguarda o resultado real.

    Use para qualquer deslocamento. 'destino' deve ser um dos comodos conhecidos.
    """
    r = get_bridge().navigate(destino)
    if r["ok"]:
        alvo = get_bridge().resolve_goal(destino) or destino
        _mundo().chegou_em(alvo)
    return _r(r["ok"], r["detail"])


@tool
def status_navegacao() -> str:
    """Informa onde o robo esta no mapa e a distancia ate cada comodo conhecido."""
    b = get_bridge()
    pose = b.map_pose()
    if pose is None:
        return _r(False, "TF map->base_link indisponivel (SLAM/Nav2 nao prontos).")
    partes = [f"Robo em x={pose[0]:.2f}, y={pose[1]:.2f} (comodo atual: {_mundo().sala_atual})"]
    for nome in b.goals:
        d = b._distance_to_goal(nome)
        if d is not None:
            partes.append(f"{nome}: {d:.2f}m")
    return _r(True, " | ".join(partes))


# ------------------------------------------------------- manobras de recuperacao

@tool
def dar_re(distancia_m: float = 0.5) -> str:
    """Recua o robo em linha reta pela distancia dada em metros.

    Use para desencostar o robo de uma parede ou obstaculo antes de tentar
    navegar de novo.
    """
    r = get_bridge().backup(distance=distancia_m)
    return _r(r["ok"], r["detail"])


@tool
def girar(graus: float) -> str:
    """Gira o robo no proprio eixo. Positivo para a esquerda, negativo para a direita.

    Use depois de dar re, para apontar o robo numa direcao livre.
    """
    r = get_bridge().spin(math.radians(float(graus)))
    return _r(r["ok"], r["detail"])


# ----------------------------------------------------------------- percepcao

@tool
def procurar_pessoa_na_sala(nome: str) -> str:
    """Procura uma pessoa APENAS no comodo onde o robo esta agora.

    Nao se desloca. Para procurar pela casa, navegue até um comodo e chame
    esta ferramenta, comodo por comodo.
    """
    m = _mundo()
    sala = m.sala_atual
    if m.pessoa_na_sala(nome, sala):
        m.registrar_pessoa(nome, sala)
        return _r(True, f"'{nome}' encontrada em '{sala}'.")
    # Resultado negativo NAO e falha de execucao: a acao de olhar funcionou.
    # A secao 7.2 do projeto trata 'not_found' como continuacao do plano
    # (ir ao proximo comodo), nao como motivo de replanejamento.
    return f"VAZIO: '{nome}' nao esta em '{sala}'. Procure em outro comodo."


@tool
def procurar_objeto_na_sala(objeto: str) -> str:
    """Procura um objeto APENAS no comodo onde o robo esta agora.

    Nao se desloca. Para varrer a casa, navegue e chame esta ferramenta em
    cada comodo.
    """
    m = _mundo()
    sala = m.sala_atual
    if m.objeto_na_sala(objeto, sala):
        p = m.peso(objeto, sala)
        extra = f" Pesa {p} kg." if p is not None else ""
        m.registrar_objeto(objeto, sala)
        return _r(True, f"'{objeto}' encontrado em '{sala}'.{extra}")
    return f"VAZIO: '{objeto}' nao esta em '{sala}'. Procure em outro comodo."


# -------------------------------------------------------------- manipulacao

@tool
def pegar_objeto(objeto: str) -> str:
    """Pega um objeto que esteja no comodo atual do robo.

    Falha se o objeto nao estiver ali, se o robo ja estiver com as maos
    ocupadas, ou se o objeto for pesado demais.
    """
    ok, motivo = _mundo().pegar(objeto)
    return _r(ok, motivo)


@tool
def entregar_objeto(objeto: str, destino: str = "") -> str:
    """Entrega o objeto que o robo esta carregando no comodo atual (ou no destino dado).

    Navegue ate o lugar da entrega ANTES de chamar esta ferramenta.
    """
    m = _mundo()
    local = destino or m.sala_atual
    ok, motivo = m.entregar(objeto, local)
    return _r(ok, motivo)


# ------------------------------------------------------- interacao e conhecimento

@tool
def falar(mensagem: str) -> str:
    """Fala uma frase para o usuario pelo modulo de TTS (topico /tts).

    Use para reportar conclusao, pedir passagem ou avisar de um problema.
    """
    r = get_bridge().falar(mensagem)
    _mundo().registrar_fala(mensagem)
    return _r(r["ok"], r["detail"])


@tool
def consultar_base(pergunta: str) -> str:
    """Consulta o conhecimento do robo sobre a casa: quais comodos existem,
    que objetos ha num comodo e quanto pesam, e onde uma pessoa foi vista.

    Use ANTES de planejar uma busca, para saber em que comodos procurar.
    """
    m = _mundo()
    q = (pergunta or "").lower()

    if any(k in q for k in ["comodo", "cômodo", "sala", "room", "onde procurar", "quais lugares"]):
        return _r(True, f"Comodos navegaveis: {', '.join(m.salas())}.")

    for sala in m.salas():
        if sala in q:
            leves = m.objetos_leves_em(sala)
            return _r(True, f"Em '{sala}' o robo consegue carregar: {', '.join(leves[:12])}.")

    if "peso" in q or "pesa" in q or "carreg" in q:
        return _r(True, f"O robo carrega no maximo {PESO_MAXIMO_KG} kg.")

    return _r(True, (f"Comodos navegaveis: {', '.join(m.salas())}. "
                     f"Capacidade de carga: {PESO_MAXIMO_KG} kg."))


# Toolkit entregue ao Agente de Execucao via bind_tools
TOOLKIT = [
    navegar_para,
    status_navegacao,
    dar_re,
    girar,
    procurar_pessoa_na_sala,
    procurar_objeto_na_sala,
    pegar_objeto,
    entregar_objeto,
    falar,
    consultar_base,
]
TOOLS_POR_NOME = {t.name: t for t in TOOLKIT}
