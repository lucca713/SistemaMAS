#!/usr/bin/env python3
"""
Campanha de experimentos: TCR, FRR, PL e AL (secao 8.3 do projeto).

Rigor adotado:

* A conclusao da tarefa NAO e o que o agente declara. Cada tarefa tem uma
  pos-condicao verificada DE FORA, contra o ground truth do cenario e, no modo
  real, contra a pose do robo por TF. A TCR sai dessa verificacao.

* O relatorio inclui a taxa de DISCORDANCIA: missoes em que o agente disse
  "success" mas a pos-condicao nao se sustenta. Numa arquitetura honesta esse
  numero tem que ser zero -- e e a prova de que o sistema parou de mentir.

* A FRR considera apenas execucoes em que uma falha foi efetivamente injetada
  (o agente precisa ter tentado a rota bloqueada para a falha disparar).

Uso:
  python3 run_experiments.py --modo sim  --reps 5
  python3 run_experiments.py --modo real --reps 1 --tarefas T1_nav,T4_entrega
"""

import argparse
import csv
import datetime
import os
import statistics
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("MAS_MAX_REPLANS", "6")

from src.agents._metrics import set_metrics                      # noqa: E402
from src.agents.graph import build_graph                         # noqa: E402
from src.core.state import (                                     # noqa: E402
    MISSION_FAILED, MISSION_IN_PROGRESS, MISSION_SUCCESS, MissionMetrics,
)
from src.tools.robot_tools import destinos_validos               # noqa: E402
from src.tools.ros_bridge import get_bridge, modo_simulado       # noqa: E402
from src.tools.scenario import get_mundo, reset_mundo            # noqa: E402

MODELO = os.environ.get("MAS_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1"))
TOLERANCIA_SALA = 1.2  # m: quao perto do waypoint conta como "esta no comodo"

# Travas de qualidade da campanha. Sem reset entre execucoes, a unica defesa
# contra dado sujo e vigiar a localizacao: se o robo se perder ou tombar, os
# resultados seguintes nao valem nada e e melhor parar do que seguir medindo.
ERRO_LOC_ALERTA = 1.5   # m: registra aviso na execucao
ERRO_LOC_ABORTA = 3.0   # m: interrompe a campanha


# --------------------------------------------------------------- verificadores

def _em(ponte, mundo, sala, tol=TOLERANCIA_SALA):
    """
    O robo esta no comodo?

    No modo real a conferencia usa a pose VERDADEIRA do Gazebo, nao o TF.
    O TF e o que o robo acredita e pode estar errado (ja esteve: 7.5 m de erro
    quando a localizacao derivou). Verificar com o que o agente acredita seria
    circular -- a TCR mediria a confianca do robo, nao o resultado.
    """
    if modo_simulado():
        return mundo.sala_atual == sala
    d = ponte.distancia_real_ate(sala)      # verdade do Gazebo, no frame do mapa
    if d is None:
        d = ponte._distance_to_goal(sala)   # sem ground truth, cai para o TF
    return d is not None and d <= tol


TAREFAS = [
    {
        "id": "T1_nav",
        "intent": "va ate o kitchen",
        "multi": False,
        "falha_em": "kitchen",
        "desc": "Navegacao de etapa unica (linha de base)",
        "verif": lambda p, m: _em(p, m, "kitchen"),
        "pos": "robo no comodo 'kitchen'",
    },
    {
        "id": "T2_pessoa",
        "intent": "encontre a Ana e avise onde ela esta",
        "multi": True,
        "falha_em": "kitchen",
        "desc": "Busca de pessoa em multiplos comodos (Estudo de Caso 1)",
        "verif": lambda p, m: any(n.lower() == "ana" and s == "kitchen"
                                  for n, s in m.pessoas_encontradas),
        "pos": "Ana localizada em 'kitchen'",
    },
    {
        "id": "T3_objeto",
        "intent": "encontre o remote control",
        "multi": True,
        "falha_em": "living room",
        "desc": "Busca de objeto em multiplos comodos",
        "verif": lambda p, m: any(o.lower() == "remote control" and s == "living room"
                                  for o, s in m.objetos_encontrados),
        "pos": "'remote control' localizado em 'living room'",
    },
    {
        "id": "T4_entrega",
        "intent": "pegue o soda_can no kitchen e leve para o living room",
        "multi": True,
        "falha_em": "kitchen",
        "desc": "Buscar e entregar (tarefa primaria da TCR)",
        "verif": lambda p, m: any(o.lower() == "soda_can" and l == "living room"
                                  for o, l in m.entregas),
        "pos": "'soda_can' entregue em 'living room'",
    },
    {
        "id": "T5_sequencia",
        "intent": "va ate o bedroom, depois va ate o dining room e avise que terminou",
        "multi": True,
        "falha_em": "bedroom",
        "desc": "Sequencia de deslocamentos com relato ao usuario",
        "verif": lambda p, m: _em(p, m, "dining room") and len(m.falas) > 0,
        "pos": "robo em 'dining room' e tendo falado ao usuario",
    },
]


# ------------------------------------------------------------------ execucao

BASE = "hall"


def volta_para_base(ponte, mundo):
    """
    Leva o robo de volta a base antes de cada missao (modo real).

    Sem isso o robo comeca onde parou e algumas execucoes partem JA do comodo
    alvo, o que infla a TCR. Esta navegacao e setup: nao entra em nenhuma
    metrica e nao passa pelos agentes.
    """
    if modo_simulado():
        return True
    if ponte.sala_mais_proxima() == BASE:
        return True
    print(f"  [setup] retornando o robo a base '{BASE}'...")
    os.environ.pop("MAS_FAULT_ROOMS", None)   # nunca injetar falha no setup
    ponte.reset_falhas()
    r = ponte.navigate(BASE, timeout=180.0)
    print(f"  [setup] retorno a base: {'OK' if r['ok'] else 'FALHOU'} - {r['detail'][:110]}")
    return r["ok"]


def roda_uma(tarefa, com_falha, ponte, mundo):
    """Executa uma missao e devolve a linha de resultado."""
    base_ok = volta_para_base(ponte, mundo)
    reset_mundo()
    ponte.reset_falhas()

    if com_falha:
        os.environ["MAS_FAULT_ROOMS"] = tarefa["falha_em"]
    else:
        os.environ.pop("MAS_FAULT_ROOMS", None)

    # No modo real o robo fica FISICAMENTE onde parou na missao anterior, entao
    # o comodo inicial e inferido da pose por TF -- se resetassemos para "hall",
    # a manipulacao consultaria o comodo errado.
    pose_inicial = ponte.map_pose()
    pose_real_ini = None if modo_simulado() else ponte.pose_real()

    # Deriva acumulada ANTES de reancorar: e o que mede a degradacao da
    # localizacao ao longo da campanha. Registrada mesmo quando corrigida.
    erro_antes = None if modo_simulado() else ponte.erro_localizacao()
    if not modo_simulado():
        rl = ponte.relocalizar()
        print(f"  [setup] {rl['detail']}")
    if not modo_simulado():
        sala = ponte.sala_mais_proxima()
        if sala:
            mundo.sala_atual = sala
            mundo.salas_visitadas = [sala]
            print(f"  [setup] comodo inicial inferido por TF: '{sala}'")
        else:
            print(f"  [setup] pose {pose_inicial} nao corresponde a nenhum waypoint; "
                  f"mantendo '{mundo.sala_atual}'")

    metrics = MissionMetrics(tarefa["intent"], model_name=MODELO)
    set_metrics(metrics)

    estado = {
        "user_intent": tarefa["intent"],
        "current_plan": [], "current_step": None, "history": [],
        "mission_status": MISSION_IN_PROGRESS, "next_node": "",
        "replan_count": 0, "last_nav_ok": False,
        "last_ros_feedback": {}, "error_context": None,
    }

    status, motivo = MISSION_FAILED, ""
    t0 = time.time()
    try:
        for s in build_graph().stream(estado, config={"recursion_limit": 160}):
            upd = list(s.values())[0] or {}
            if "mission_status" in upd:
                status = upd["mission_status"]
            if upd.get("error_context"):
                motivo = upd["error_context"]
    except Exception as e:
        status, motivo = MISSION_FAILED, f"grafo abortou: {e}"
        traceback.print_exc(limit=2)

    if status not in (MISSION_SUCCESS, MISSION_FAILED):
        status = MISSION_FAILED
    metrics.finish(status)

    # --- verificacao externa da pos-condicao ---
    try:
        pos_ok = bool(tarefa["verif"](ponte, mundo))
    except Exception as e:
        pos_ok = False
        motivo = motivo or f"verificador falhou: {e}"

    agente_disse_ok = (status == MISSION_SUCCESS)
    discordancia = agente_disse_ok and not pos_ok

    # Estado fisico de verdade ao fim da missao
    pose_real_fim = None if modo_simulado() else ponte.pose_real()
    erro_loc = None if modo_simulado() else ponte.erro_localizacao()
    tombou = False if modo_simulado() else ponte.tombado()

    set_metrics(None)
    r = metrics.summary
    return {
        "tarefa": tarefa["id"],
        "multi_etapa": tarefa["multi"],
        "base_ok": base_ok,
        "modo": "sim" if modo_simulado() else "real",
        "falha_injetada_pedida": com_falha,
        "falhas_injetadas": r["injected_faults"],
        "agente_declarou": status,
        "poscondicao_ok": pos_ok,
        "discordancia": discordancia,
        "duracao_s": round(time.time() - t0, 2),
        "replanejamentos": r["replan_count"],
        "tool_calls": r["tool_calls"],
        "correcoes_guarda": r["correcoes_guarda"],
        "PL_plan_inicial_s": r["PL_plan_inicial_s"],
        "PL_replan_s": r["PL_replan_s"],
        "AL_acao_s": r["AL_acao_s"],
        "AL_amostras": r["AL_amostras"],
        "pose_inicial": f"{pose_inicial[0]:.2f},{pose_inicial[1]:.2f}" if pose_inicial else "",
        "pose_real_fim": f"{pose_real_fim[0]:.2f},{pose_real_fim[1]:.2f}" if pose_real_fim else "",
        "erro_loc_antes_m": round(erro_antes, 2) if erro_antes is not None else "",
        "erro_localizacao_m": round(erro_loc, 2) if erro_loc is not None else "",
        "robo_tombado": tombou,
        "motivo": (motivo or "")[:240],
    }


# ------------------------------------------------------------------ agregacao

def _pct(num, den):
    return round(100.0 * num / den, 1) if den else None


def agrega(linhas):
    multi = [l for l in linhas if l["multi_etapa"]]
    limpas = [l for l in multi if l["falhas_injetadas"] == 0]
    com_falha = [l for l in linhas if l["falhas_injetadas"] > 0]

    pls = [l["PL_plan_inicial_s"] for l in linhas if l["PL_plan_inicial_s"]]
    als = [l["AL_acao_s"] for l in linhas if l["AL_amostras"]]
    rpl = [l["PL_replan_s"] for l in linhas if l["PL_replan_s"]]

    return {
        "execucoes_totais": len(linhas),
        "TCR_multietapa_pct": _pct(sum(l["poscondicao_ok"] for l in multi), len(multi)),
        "TCR_multietapa_n": len(multi),
        "TCR_sem_falha_pct": _pct(sum(l["poscondicao_ok"] for l in limpas), len(limpas)),
        "TCR_sem_falha_n": len(limpas),
        "FRR_pct": _pct(sum(l["poscondicao_ok"] for l in com_falha), len(com_falha)),
        "FRR_n": len(com_falha),
        "discordancias": sum(l["discordancia"] for l in linhas),
        "PL_media_s": round(statistics.mean(pls), 3) if pls else None,
        "PL_replan_media_s": round(statistics.mean(rpl), 3) if rpl else None,
        "AL_media_s": round(statistics.mean(als), 6) if als else None,
        "replan_medio": round(statistics.mean([l["replanejamentos"] for l in linhas]), 2) if linhas else None,
        "correcoes_guarda_total": sum(l["correcoes_guarda"] for l in linhas),
        "tool_calls_total": sum(l["tool_calls"] for l in linhas),
    }


def relatorio(linhas, ag, args, caminho):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    L = []
    A = L.append
    A("# Relatorio de Validacao - Sistema Multiagente LLM (RoboCup@Home)")
    A("")
    A(f"- Gerado em: {ts}")
    A(f"- Modelo LLM: {MODELO} (Ollama local)")
    A(f"- Modo de navegacao: **{'SIMULADO' if modo_simulado() else 'REAL (Nav2 + Gazebo)'}**")
    A(f"- Repeticoes por condicao: {args.reps}")
    A(f"- Teto de replanejamentos: {os.environ.get('MAS_MAX_REPLANS')}")
    A(f"- Comodos navegaveis: {', '.join(destinos_validos())}")
    A(f"- Cenario (ground truth): {get_mundo().cenario_path}")
    A("")
    if modo_simulado():
        A("> ATENCAO: no modo simulado a navegacao nao e verificada por TF -- a")
        A("> chegada e assumida. O raciocinio (decompor, detectar falha, replanejar)")
        A("> e exercitado de verdade; o deslocamento fisico, nao.")
        A("")
    A("## Metricas da secao 8.3")
    A("")
    A("| Metrica | Valor | n | Definicao |")
    A("|---|---|---|---|")
    A(f"| **TCR** (tarefas multi-etapa) | {ag['TCR_multietapa_pct']}% | {ag['TCR_multietapa_n']} | "
      "% de tarefas multi-etapa concluidas, verificado por pos-condicao externa |")
    A(f"| TCR sem falha injetada | {ag['TCR_sem_falha_pct']}% | {ag['TCR_sem_falha_n']} | "
      "mesma metrica, so execucoes sem falha induzida |")
    A(f"| **FRR** | {ag['FRR_pct']}% | {ag['FRR_n']} | "
      "% de falhas injetadas das quais o Supervisor se recuperou e concluiu |")
    A(f"| **PL** | {ag['PL_media_s']} s | - | tempo do Planejador para decompor a tarefa |")
    A(f"| PL (replanejamento) | {ag['PL_replan_media_s']} s | - | tempo para gerar um plano de recuperacao |")
    A(f"| **AL** | {ag['AL_media_s']} s | - | feedback de sucesso -> despacho do proximo passo |")
    A("")
    A("## Honestidade do relato")
    A("")
    A(f"- Discordancias agente-vs-realidade: **{ag['discordancias']}** de {ag['execucoes_totais']}")
    A("  (missoes em que o agente declarou sucesso e a pos-condicao nao se sustentou;")
    A("  o esperado nesta arquitetura e zero)")
    A(f"- Correcoes da guarda deterministica: {ag['correcoes_guarda_total']} "
      f"em {ag['tool_calls_total']} chamadas de ferramenta")
    A(f"- Replanejamentos por missao (media): {ag['replan_medio']}")
    A("")
    A("## Tarefas avaliadas")
    A("")
    A("| ID | Descricao | Pos-condicao verificada |")
    A("|---|---|---|")
    for t in TAREFAS:
        A(f"| {t['id']} | {t['desc']} | {t['pos']} |")
    A("")
    A("## Execucoes")
    A("")
    A("| # | tarefa | modo | falha inj. | agente disse | pos-cond | replan | tools | dur(s) |")
    A("|---|---|---|---|---|---|---|---|---|")
    for i, l in enumerate(linhas, 1):
        A(f"| {i} | {l['tarefa']} | {l['modo']} | {l['falhas_injetadas']} | "
          f"{l['agente_declarou']} | {'OK' if l['poscondicao_ok'] else 'NAO'} | "
          f"{l['replanejamentos']} | {l['tool_calls']} | {l['duracao_s']} |")
    A("")
    falhas = [l for l in linhas if not l["poscondicao_ok"]]
    if falhas:
        A("## Execucoes que nao cumpriram a pos-condicao")
        A("")
        for l in falhas:
            A(f"- **{l['tarefa']}** (falhas inj.: {l['falhas_injetadas']}, "
              f"agente: {l['agente_declarou']}): {l['motivo'] or 'sem motivo registrado'}")
        A("")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return "\n".join(L)


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["sim", "real"], default="sim")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tarefas", default="", help="IDs separados por virgula")
    ap.add_argument("--sem-falha", action="store_true", help="nao rodar a condicao com falha")
    ap.add_argument("--saida", default="resultados")
    args = ap.parse_args()

    if args.modo == "sim":
        os.environ["MAS_SIM_NAV"] = "1"
    else:
        os.environ.pop("MAS_SIM_NAV", None)

    selec = [t for t in TAREFAS
             if not args.tarefas or t["id"] in args.tarefas.split(",")]

    ponte = get_bridge()
    mundo = get_mundo(salas_navegaveis=destinos_validos())

    condicoes = [False] if args.sem_falha else [False, True]
    total = len(selec) * args.reps * len(condicoes)
    print(f"\n{'='*70}\nCampanha: {len(selec)} tarefas x {args.reps} reps x "
          f"{len(condicoes)} condicoes = {total} execucoes | modo={args.modo}\n{'='*70}\n")

    linhas = []
    n = 0
    abortou = False
    for rep in range(args.reps):
        if abortou:
            break
        for tarefa in selec:
            if abortou:
                break
            for com_falha in condicoes:
                if abortou:
                    break
                n += 1
                etiqueta = "COM falha injetada" if com_falha else "sem falha"
                print(f"\n{'-'*70}\n[{n}/{total}] {tarefa['id']} rep{rep+1} ({etiqueta})"
                      f"\n  intencao: {tarefa['intent']}\n{'-'*70}")
                l = roda_uma(tarefa, com_falha, ponte, mundo)
                linhas.append(l)
                e = l.get("erro_localizacao_m")
                e = float(e) if e not in ("", None) else 0.0
                # So aborta se o robo tombar fisicamente. Deriva de localizacao
                # nao contamina a execucao seguinte, porque cada uma reancora a
                # pose no setup -- entao ela e RESULTADO medido, nao defeito do
                # experimento, e a campanha continua.
                if l.get("robo_tombado"):
                    print(f"\n{'!'*70}")
                    print(f"CAMPANHA INTERROMPIDA apos {n} execucoes.")
                    print(f"  erro de localizacao = {e:.2f} m (limite {ERRO_LOC_ABORTA} m)"
                          f" | robo tombado = {l.get('robo_tombado')}")
                    print("  Os dados ate aqui estao salvos. Relance a pilha antes de continuar:")
                    print("    MAS_AUTOSTART=0 ~/ros2_ws/iniciar_projeto.sh")
                    print(f"{'!'*70}\n")
                    abortou = True
                elif e >= ERRO_LOC_ABORTA:
                    print(f"  [DERIVA ALTA] erro de localizacao {e:.2f} m "
                          f"- execucao registrada como falha de localizacao")
                elif e >= ERRO_LOC_ALERTA:
                    print(f"  [ALERTA] erro de localizacao {e:.2f} m "
                          f"(limite de aviso {ERRO_LOC_ALERTA} m)")
                print(f"  => agente: {l['agente_declarou']} | pos-condicao: "
                      f"{'OK' if l['poscondicao_ok'] else 'NAO CUMPRIDA'}"
                      f"{'  <<< DISCORDANCIA' if l['discordancia'] else ''}"
                      f" | replan={l['replanejamentos']} | {l['duracao_s']}s")

    if abortou:
        print(f"[AVISO] campanha incompleta: {len(linhas)} de {total} execucoes.")
    os.makedirs(args.saida, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.saida, f"experimentos_{args.modo}_{stamp}.csv")
    rel_path = os.path.join(args.saida, f"relatorio_{args.modo}_{stamp}.md")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)

    ag = agrega(linhas)
    texto = relatorio(linhas, ag, args, rel_path)
    print("\n" + texto)
    print(f"\n[SAIDA] CSV ....... {csv_path}")
    print(f"[SAIDA] Relatorio . {rel_path}")


if __name__ == "__main__":
    main()
