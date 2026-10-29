"""
Agente de Execucao (padrao ROSA): recebe UM passo do Supervisor e invoca a
ferramenta ROS 2 correspondente.

Diferencas para a versao anterior:
- Tool calling NATIVO via bind_tools, em vez de pedir uma string
  ("NAVIGATE: x") e fatiar com split(':'). Aquele parsing quebrava toda vez
  que o llama3.1 respondia qualquer coisa fora do formato, e o galho 'else'
  mandava a frase inteira como se fosse nome de sala.
- Fallback deterministico: se o modelo nao emitir tool call, a gente resolve
  por regra. O passo nunca vira uma navegacao para um destino inventado.
- O feedback devolvido e o que a ferramenta realmente apurou. Nada de assumir
  sucesso.
"""

import os
import re

from langchain_ollama import ChatOllama

from src.agents._metrics import get_metrics
from src.core.state import AgentState
from src.tools.robot_tools import TOOLKIT, TOOLS_POR_NOME, destinos_validos

MODELO = os.environ.get("MAS_MODEL", "llama3.1")

SISTEMA = """Voce e o sistema de execucao de um robo de servico.
Recebe UMA acao e deve chamar exatamente UMA ferramenta que a realize.

Comodos validos do mapa: {destinos}

Mapeamento:
- ir/deslocar-se a um comodo        -> navegar_para(destino)
- procurar uma PESSOA               -> procurar_pessoa_na_sala(nome)
- procurar um OBJETO                -> procurar_objeto_na_sala(objeto)
- pegar/agarrar um objeto           -> pegar_objeto(objeto)
- entregar/deixar um objeto         -> entregar_objeto(objeto, destino)
- falar/avisar/dizer                -> falar(mensagem)
- recuar / dar re                   -> dar_re(distancia_m)
- girar / virar                     -> girar(graus); esquerda positivo, direita negativo
- saber onde esta                   -> status_navegacao()
- saber quais comodos ou pesos      -> consultar_base(pergunta)

Nunca invente um comodo fora da lista. Chame a ferramenta, nao responda em texto."""


def _fallback(passo: str):
    """Resolve o passo por regra quando o LLM nao emite tool call."""
    t = (passo or "").lower()

    if re.search(r"\b(dar re|dar ré|recu|re\b|ré\b|tras|trás|back)", t):
        return "dar_re", {"distancia_m": 0.5}

    if re.search(r"\b(gir|vir|rotac|turn)", t):
        return "girar", {"graus": -90.0 if re.search(r"direita|right", t) else 90.0}

    if re.search(r"\b(fal|diz|avis|inform|anunc)", t):
        return "falar", {"mensagem": passo}

    if re.search(r"\b(peg|agarr|apanh|pick)", t):
        alvo = re.sub(r".*?\b(?:pegar|pegue|peg[ae]|agarrar|apanhar|pick up|pick)\b\s*", "", t).strip(" .,")
        return ("pegar_objeto", {"objeto": alvo}) if alvo else (None, None)

    if re.search(r"\b(entreg|deix|deliver|dar para)", t):
        alvo = re.sub(r".*?\b(?:entregar|entregue|deixar|deixe|deliver)\b\s*", "", t)
        alvo = re.split(r"\b(?:em|no|na|para|ao)\b", alvo)[0].strip(" .,")
        destino = ""
        for d in destinos_validos():
            if d.lower() in t:
                destino = d
                break
        return "entregar_objeto", {"objeto": alvo, "destino": destino}

    if re.search(r"\b(procur|busc|ache|achar|encontr|look for|search)", t):
        objeto = "objeto" in t
        alvo = re.sub(r".*?\b(?:procurar|procure|buscar|busque|ache|achar|encontrar|encontre)\b\s*", "", t)
        alvo = re.sub(r"^(?:o |a |objeto )+", "", alvo)
        alvo = re.split(r"\b(?:na sala|no comodo|no cômodo|na|no|em)\b", alvo)[0].strip(" .,")
        if alvo:
            return ("procurar_objeto_na_sala", {"objeto": alvo}) if objeto \
                else ("procurar_pessoa_na_sala", {"nome": alvo})

    if re.search(r"\bonde (eu |o robo )?est", t):
        return "status_navegacao", {}

    # Navegacao: casa o texto do passo com algum comodo conhecido.
    for destino in destinos_validos():
        if destino.lower() in t:
            return "navegar_para", {"destino": destino}

    if re.search(r"\b(ir|va|vá|nave|dirig|segu|and)", t):
        alvo = re.sub(r".*?\b(?:ate|até|para|ao|a|no|na|em)\b\s+", "", t).strip(" .,")
        if alvo:
            return "navegar_para", {"destino": alvo}

    return None, None


def _guarda(passo: str, nome, args):
    """
    Corrige escolhas do LLM que contradizem sinais lexicais fortes do passo.

    Nos testes o llama3.1 erra de forma reproduzivel em dois pontos: confunde
    "pegar X" com "procurar X", e inverte o sinal do giro ("para a direita"
    virando +90). A guarda conserta e DEVOLVE o motivo, para que a taxa de
    correcao deterministica entre nas metricas em vez de ficar escondida.
    """
    t = (passo or "").lower()
    args = dict(args or {})
    motivo = None

    # 1. pegar nao e procurar
    if re.search(r"\b(peg|agarr|apanh|pick up)", t) and nome != "pegar_objeto":
        n2, a2 = _fallback(passo)
        if n2 == "pegar_objeto":
            return n2, a2, "LLM escolheu busca para um passo de 'pegar'"

    # 2. numeros vindo como string + sentido do giro
    if nome == "girar":
        try:
            g = float(args.get("graus", 90))
        except (TypeError, ValueError):
            g = 90.0
        if re.search(r"direita|right", t) and g > 0:
            g, motivo = -abs(g), "sinal do giro invertido (direita e negativo)"
        elif re.search(r"esquerda|left", t) and g < 0:
            g, motivo = abs(g), "sinal do giro invertido (esquerda e positivo)"
        args["graus"] = g

    if nome == "dar_re":
        try:
            args["distancia_m"] = float(args.get("distancia_m", 0.5))
        except (TypeError, ValueError):
            args["distancia_m"] = 0.5

    return nome, args, motivo


def execute_node(state: AgentState) -> dict:
    passo = state.get("current_step")
    print(f"--- [Executor] Passo recebido: '{passo}' ---")

    llm = ChatOllama(model=MODELO, temperature=0).bind_tools(TOOLKIT)

    nome, args = None, None
    try:
        resp = llm.invoke([
            ("system", SISTEMA.format(destinos=", ".join(destinos_validos()))),
            ("human", f"Acao: {passo}"),
        ])
        chamadas = getattr(resp, "tool_calls", None) or []
        if chamadas:
            nome = chamadas[0]["name"]
            args = chamadas[0].get("args", {}) or {}
            print(f"--- [Executor] LLM chamou a tool: {nome}({args}) ---")
        else:
            print(f"--- [Executor] LLM nao chamou tool (respondeu: {str(resp.content)[:80]!r}) ---")
    except Exception as e:
        print(f"--- [Executor] Erro ao consultar o LLM: {e} ---")

    if nome not in TOOLS_POR_NOME:
        nome, args = _fallback(passo)
        if nome:
            print(f"--- [Executor] Fallback deterministico: {nome}({args}) ---")

    if nome in TOOLS_POR_NOME:
        nome, args, correcao = _guarda(passo, nome, args)
        if correcao:
            print(f"--- [Executor] GUARDA corrigiu: {correcao} -> {nome}({args}) ---")
            m = get_metrics()
            if m is not None:
                m.record_correction(correcao)

    if nome not in TOOLS_POR_NOME:
        motivo = f"Nao consegui traduzir o passo '{passo}' em nenhuma ferramenta conhecida."
        print(f"--- [Executor] {motivo} ---")
        return {
            "history": [f"Executado: {passo} -> FALHA ({motivo})"],
            "last_ros_feedback": {"status": "error", "reason": motivo, "stuck": False},
        }

    # Executa a ferramenta de verdade.
    try:
        saida = TOOLS_POR_NOME[nome].invoke(args)
    except Exception as e:
        saida = f"FALHA: excecao ao executar {nome}: {e}"

    travado = "TRAVADO" in saida.upper()
    if saida.startswith("SUCESSO"):
        status = "success"
    elif saida.startswith("VAZIO"):
        status = "empty"      # procurou e nao achou: passo concluido, plano segue
    else:
        status = "error"

    print(f"--- [Executor] Resultado real: {saida} ---")

    return {
        "history": [f"Executado: {passo} via {nome} -> {status} ({saida})"],
        "last_ros_feedback": {
            "status": status,
            "reason": saida,
            "stuck": travado,
            "tool": nome,
            "args": args,
        },
    }
