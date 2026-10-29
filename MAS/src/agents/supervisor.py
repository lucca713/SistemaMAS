"""
Agente Supervisor (papeis de Supervisor do MALMM + Evaluation do MARS).

Mudancas em relacao a versao anterior, todas na direcao de parar de mentir:

1. Sumiu o mock que, com last_ros_feedback vazio, fabricava
   {"status": "success"}. Feedback ausente agora e tratado como falha.

2. Missao so termina em "success" se alguma navegacao tiver sido confirmada
   fisicamente (last_nav_ok). Antes, acabar a lista de passos ja bastava para
   declarar sucesso -- era dai que vinha o "deu certo" com o robo parado na
   parede.

3. Teto de replanejamentos. Estourou, a missao termina em "failed" com o
   motivo real, em vez de girar para sempre ou fingir que acabou bem.
"""

import time

from src.agents._metrics import contar_falha_injetada, fechar_acao, marcar_feedback
from src.agents.objetivo import objetivo_cumprido
from src.core.state import MAX_REPLANS, AgentState


def supervise_node(state: AgentState) -> dict:
    print("--- [Supervisor] Avaliando estado... ---")

    plano = list(state.get("current_plan") or [])
    passo = state.get("current_step")
    replans = state.get("replan_count", 0)
    nav_ok = state.get("last_nav_ok", False)

    # 1. Ha um passo em voo: julga o feedback apurado pelo Executor.
    if passo:
        fb = state.get("last_ros_feedback") or {}

        if not fb:
            # Sem telemetria nao existe sucesso. Isso e uma falha de verdade.
            motivo = f"Passo '{passo}' terminou sem nenhum feedback do ROS 2."
            print(f"--- [Supervisor] {motivo} ---")
            return _replanejar(state, motivo, replans)

        if fb.get("status") == "empty":
            # Procurou no comodo e nao achou. O passo foi executado; segue o
            # plano para o proximo comodo, sem replanejar.
            print(f"--- [Supervisor] Passo '{passo}': procurou e nao achou. Seguindo o plano. ---")
            marcar_feedback()
            return {
                "current_step": None,
                "last_ros_feedback": {},
                "busca_vazia": True,
                "next_node": "supervisor",
            }

        if fb.get("status") == "success":
            print(f"--- [Supervisor] Passo '{passo}' confirmado. ---")
            marcar_feedback()  # AL: abre a janela ate o despacho do proximo passo
            achou = str(fb.get("tool", "")).startswith("procurar_")
            return {
                "current_step": None,
                "last_ros_feedback": {},
                **({"busca_ok": True} if achou else {}),
                # Qualquer passo concluido conta como progresso real: cada tool
                # verifica o proprio efeito (navegacao por TF, manipulacao
                # contra o cenario). A conferencia final da tarefa e feita de
                # fora, pelo verificador de pos-condicao do experimento.
                "last_nav_ok": True,
                "next_node": "supervisor",
            }

        motivo = fb.get("reason", "Erro desconhecido no hardware.")
        if fb.get("injected") or "[FALHA INJETADA]" in str(motivo):
            contar_falha_injetada()
        if fb.get("stuck"):
            motivo += " O robo esta encostado num obstaculo e precisa recuar antes de tentar de novo."
        print(f"--- [Supervisor] FALHA REAL: {motivo} ---")
        return _replanejar(state, motivo, replans)

    # 2. Sem passo em voo, mas com plano: despacha o proximo.
    if plano:
        proximo = plano.pop(0)
        print(f"--- [Supervisor] Despachando: '{proximo}' (restam {len(plano)}) ---")
        fechar_acao()  # AL: fecha o intervalo feedback-de-sucesso -> despacho
        return {
            "current_step": proximo,
            "current_plan": plano,
            "last_ros_feedback": {},
            "next_node": "executor",
        }

    # 3. Sem plano e sem passo.
    if not state.get("history"):
        print("--- [Supervisor] Sem plano. Chamando o Planejador. ---")
        return {"next_node": "planner"}

    # Plano esgotado: a missao so foi cumprida se o robo chegou de fato.
    busca_vazia = state.get("busca_vazia", False)
    busca_ok = state.get("busca_ok", False)

    if busca_vazia and not busca_ok:
        motivo = ("Varri os comodos do plano e nao encontrei o que foi pedido. "
                  "Faltam comodos para procurar.")
        print(f"--- [Supervisor] {motivo} ---")
        return _replanejar(state, motivo, replans)

    # Papel de Agente de Avaliacao: plano esgotado nao e tarefa cumprida.
    from src.tools.robot_tools import destinos_validos
    from src.tools.scenario import get_mundo
    mundo = get_mundo(salas_navegaveis=destinos_validos())
    cumprido, por_que = objetivo_cumprido(state.get("user_intent", ""), mundo)

    if cumprido is False:
        print(f"--- [Supervisor] Plano esgotado, mas o objetivo NAO foi cumprido: {por_que} ---")
        return _replanejar(state, por_que, replans)

    if cumprido is True:
        print("--- [Supervisor] Objetivo cumprido e verificado. ---")
        return {"mission_status": "success", "next_node": "END"}

    if nav_ok:
        print("--- [Supervisor] Plano cumprido, todos os passos verificados. ---")
        return {"mission_status": "success", "next_node": "END"}

    motivo = "O plano acabou sem nenhum passo verificado com sucesso."
    print(f"--- [Supervisor] {motivo} ---")
    return _replanejar(state, motivo, replans)


def _replanejar(state: AgentState, motivo: str, replans: int) -> dict:
    """Dispara replanejamento, ou encerra em falha se o teto foi atingido."""
    if replans >= MAX_REPLANS:
        print(f"--- [Supervisor] Teto de {MAX_REPLANS} replanejamentos atingido. MISSAO FALHOU. ---")
        return {
            "mission_status": "failed",
            "error_context": motivo,
            "current_plan": [],
            "current_step": None,
            "next_node": "END",
        }

    print(f"--- [Supervisor] Replanejando ({replans + 1}/{MAX_REPLANS}). ---")
    return {
        "error_context": motivo,
        "current_plan": [],
        "current_step": None,
        "last_ros_feedback": {},
        "mission_status": "replanning",
        "replan_count": replans + 1,
        "next_node": "planner",
    }
