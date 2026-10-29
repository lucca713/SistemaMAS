"""
Agente de Planejamento (padrao MALMM Planner): decompoe a intencao do usuario
em passos, e replaneja quando o Supervisor reporta falha real.

Mudancas: os destinos vem do JSON de metas (nao mais chumbados no prompt), e
o parsing aceita lista por virgula, por linha ou numerada -- o llama3.1
alterna entre os tres formatos.
"""

import os
import re

from langchain_ollama import ChatOllama

from src.core.state import AgentState
from src.tools.robot_tools import destinos_validos

MODELO = os.environ.get("MAS_MODEL", "llama3.1")

PROMPT = """Voce planeja as acoes de um robo de servico domestico.

Comodos navegaveis: {destinos}
Robo esta em: {sala} | Carregando: {carregando}
Comodos JA visitados nesta missao: {visitadas}

Acoes possiveis (uma por passo):
ir ate o X | procurar NOME na sala | procurar objeto X na sala | pegar X |
entregar X em Y | falar MENSAGEM | dar re | girar para a direita

EXEMPLOS

Intencao: va ate o kitchen
Erro anterior: Nenhum
Plano: ir ate o kitchen

Intencao: encontre a Ana e avise onde ela esta
Erro anterior: Nenhum
Plano: ir ate o kitchen, procurar Ana na sala, falar encontrei a Ana

Intencao: pegue o soda_can no kitchen e leve para o living room
Erro anterior: Nenhum
Plano: ir ate o kitchen, pegar soda_can, ir ate o living room, entregar soda_can em living room

Intencao: encontre o remote control
Erro anterior: Nenhum
Plano: ir ate o living room, procurar objeto remote control na sala

Intencao: encontre o remote control
Erro anterior: Varri os comodos do plano e nao encontrei. Faltam comodos para procurar.
Plano: ir ate o bedroom, procurar objeto remote control na sala, ir ate o dining room, procurar objeto remote control na sala

Intencao: va ate o kitchen
Erro anterior: Caminho para kitchen bloqueado. O robo esta TRAVADO e precisa recuar.
Plano: dar re, girar para a direita, ir ate o kitchen

Intencao: pegue o soda_can no kitchen e leve para o living room
Erro anterior: Caminho para kitchen bloqueado. O robo esta TRAVADO e precisa recuar.
Plano: dar re, girar para a direita, ir ate o kitchen, pegar soda_can, ir ate o living room, entregar soda_can em living room

Intencao: encontre a Ana e avise onde ela esta
Erro anterior: A tarefa pedia encontrar algo e nada foi encontrado nos comodos visitados.
Comodos JA visitados: hall, living room, dining room
Plano: ir ate o kitchen, procurar Ana na sala, falar encontrei a Ana

REGRAS
1. Responda SO com a linha do plano, passos separados por virgula. Nada mais.
2. Use o minimo de passos. Nao invente acoes que a intencao nao pediu.
3. Sempre escreva o nome real da pessoa ou do objeto, nunca um rotulo genérico.
4. Se o erro anterior disser TRAVADO ou ENCOSTADO, comece com dar re e girar.
5. Se o erro anterior disser que nao encontrou, va SO para comodos que NAO estao
   na lista de ja visitados.
6. Use somente comodos da lista.
7. O plano de recuperacao tem que concluir a tarefa INTEIRA, nao so desencostar
   o robo. Depois de dar re e girar, repita os passos que ainda faltam.
8. So fale que encontrou algo DEPOIS do passo que procura.

AGORA RESPONDA

Intencao: {intent}
Erro anterior: {erro}
Historico: {history}
Plano:"""


def _parse(texto: str) -> list:
    """Extrai a lista de passos aceitando virgula, quebra de linha ou numeracao."""
    texto = (texto or "").strip()
    if not texto:
        return []

    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    # Descarta preambulo tipo "Aqui esta o plano:"
    linhas = [l for l in linhas if not l.rstrip().endswith(":")]

    if len(linhas) > 1:
        bruto = linhas
    else:
        bruto = linhas[0].split(",") if linhas else []

    passos = []
    for p in bruto:
        p = re.sub(r"^\s*[-*\d]+[\.\)]?\s*", "", p).strip(" .;\"'")
        if p:
            passos.append(p)
    return passos


def plan_node(state: AgentState) -> dict:
    print("--- [Planejador] Trabalhando... ---")

    erro = state.get("error_context")
    if erro:
        print(f"--- [Planejador] Replanejando por causa de: {erro} ---")

    llm = ChatOllama(model=MODELO, temperature=0)

    try:
        from src.tools.scenario import get_mundo
        mundo = get_mundo(salas_navegaveis=destinos_validos())
        resp = llm.invoke(PROMPT.format(
            intent=state.get("user_intent"),
            destinos=", ".join(destinos_validos()),
            sala=mundo.sala_atual,
            carregando=mundo.carregando or "nada",
            visitadas=", ".join(mundo.salas_visitadas) or "nenhum",
            history=state.get("history", [])[-5:],
            erro=erro or "Nenhum",
        ))
        conteudo = resp.content
        if isinstance(conteudo, list):
            conteudo = conteudo[0].get("text", "") if isinstance(conteudo[0], dict) else str(conteudo[0])
        plano = _parse(str(conteudo))
    except Exception as e:
        print(f"--- [Planejador] Erro ao consultar o LLM: {e} ---")
        plano = []

    if not plano:
        # Sem plano utilizavel, nao inventa sucesso: manda um passo direto com
        # a intencao crua e deixa o Executor/Supervisor apurarem o resultado.
        plano = [state.get("user_intent", "")]
        print("--- [Planejador] LLM nao produziu plano; usando a intencao crua como passo unico. ---")

    print(f"--- [Planejador] Plano: {plano} ---")
    return {"current_plan": plano, "error_context": None}
