"""
Verificacao de objetivo pelo Supervisor (papel de Agente de Avaliacao, MARS).

Por que isto existe: "plano esgotado" nao e "tarefa cumprida". Quando uma falha
dispara um replanejamento, o plano de recuperacao pode resolver so o
desencosto e abandonar o resto da tarefa. Sem esta checagem o Supervisor
declarava sucesso nessa situacao -- exatamente o tipo de mentira que a
arquitetura precisa eliminar.

Esta checagem e GENERICA: deriva o tipo de objetivo da intencao do usuario e
cobra evidencia no estado do mundo. Ela NAO conhece a resposta certa do
cenario. A conferencia com o ground truth especifico (o objeto certo no comodo
certo) e feita de fora, pelo verificador de pos-condicao do experimento, para
que a TCR nao fique circular.
"""

import re


def objetivo_cumprido(intent: str, mundo):
    """
    Devolve (cumprido, motivo).

    cumprido=None significa "esta intencao nao tem objetivo verificavel aqui":
    o Supervisor cai no criterio de navegacao (chegada confirmada por TF).
    """
    t = (intent or "").lower()

    # Entrega: exige entrega registrada.
    if re.search(r"\b(leve|levar|leva|traga|trazer|entreg)", t):
        if mundo.entregas:
            return True, ""
        if mundo.carregando:
            return False, (f"Estou carregando '{mundo.carregando}' mas ainda nao "
                           "entreguei no destino pedido.")
        return False, "A tarefa pedia uma entrega e nenhuma entrega foi feita."

    # Pegar sem entregar: exige objeto na mao.
    if re.search(r"\b(peg(a|ue|ar)?|apanh|agarr)\b", t):
        if mundo.carregando:
            return True, ""
        return False, "A tarefa pedia pegar um objeto e o robo nao esta carregando nada."

    # Busca: exige algo efetivamente encontrado.
    if re.search(r"\b(encontr|ache|achar|procur|busq|busca|localiz)", t):
        if mundo.pessoas_encontradas or mundo.objetos_encontrados:
            return True, ""
        return False, ("A tarefa pedia encontrar algo e nada foi encontrado nos "
                       "comodos visitados.")

    return None, ""
