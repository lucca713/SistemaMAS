"""Coletor de metricas ativo da missao corrente (ponteiro global simples)."""

import time

_ativo = None


def set_metrics(m):
    global _ativo
    _ativo = m


def get_metrics():
    return _ativo


def marcar_feedback():
    """Supervisor recebeu feedback de sucesso: abre a janela da AL."""
    if _ativo is not None:
        _ativo.mark_feedback(time.perf_counter())


def fechar_acao():
    """Supervisor despachou o proximo passo: fecha a janela da AL."""
    if _ativo is not None:
        _ativo.record_action_latency(time.perf_counter())


def contar_falha_injetada():
    if _ativo is not None:
        _ativo.record_injected_fault()
