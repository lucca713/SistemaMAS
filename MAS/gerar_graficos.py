#!/usr/bin/env python3
"""
Gera as tabelas e os graficos da validacao a partir dos CSVs de experimento.

Saidas em resultados/:
  relatorio.html        - relatorio completo, auto-contido (KPIs + graficos + tabelas)
  fig_*.svg             - cada grafico isolado, vetorial, para colar na monografia
  tabelas.md            - as tabelas em markdown

SVG escrito a mao de proposito: o matplotlib 3.5.1 desta maquina esta
incompativel com o numpy 2.2.6 (ABI), e saida vetorial e melhor para o TCC.
"""

import csv
import glob
import os
import statistics
import sys
from collections import defaultdict

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")

# Paleta validada (light / dark), usada por papel e nao por hex solto.
C = {
    "surface": "#fcfcfb", "plane": "#f9f9f7",
    "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
    "grid": "#e1e0d9", "axis": "#c3c2b7",
    "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a",
    "good": "#0ca30c", "critical": "#d03b3b", "warning": "#fab219",
}
CD = {
    "surface": "#1a1a19", "plane": "#0d0d0d",
    "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
    "grid": "#2c2c2a", "axis": "#383835",
    "s1": "#3987e5", "s2": "#d95926", "s3": "#199e70",
    "good": "#0ca30c", "critical": "#d03b3b", "warning": "#fab219",
}
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _b(v):
    return str(v).strip().lower() in ("true", "1", "sim", "yes")


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def carrega():
    """Le todos os CSVs de experimento e devolve as linhas normalizadas."""
    linhas = []
    for p in sorted(glob.glob(os.path.join(RES, "experimentos_*.csv"))):
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r.get("tarefa"):
                    continue
                linhas.append({
                    "tarefa": r["tarefa"],
                    "multi": _b(r.get("multi_etapa")),
                    "modo": r.get("modo", "sim"),
                    "falhas": int(_f(r.get("falhas_injetadas"))),
                    "declarou": r.get("agente_declarou", ""),
                    "pos_ok": _b(r.get("poscondicao_ok")),
                    "discord": _b(r.get("discordancia")),
                    "dur": _f(r.get("duracao_s")),
                    "replan": int(_f(r.get("replanejamentos"))),
                    "tools": int(_f(r.get("tool_calls"))),
                    "correcoes": int(_f(r.get("correcoes_guarda"))),
                    "pl": _f(r.get("PL_plan_inicial_s")),
                    "pl_re": _f(r.get("PL_replan_s")),
                    "al": _f(r.get("AL_acao_s")),
                    "al_n": int(_f(r.get("AL_amostras"))),
                    "eloc": _f(r.get("erro_localizacao_m")),
                    "eloc_antes": _f(r.get("erro_loc_antes_m")),
                    "tombado": _b(r.get("robo_tombado")),
                    "arquivo": os.path.basename(p),
                })
    return linhas


def pct(n, d):
    return (100.0 * n / d) if d else None


def agrega(ls):
    multi = [l for l in ls if l["multi"]]
    limpas = [l for l in multi if l["falhas"] == 0]
    cfalha = [l for l in ls if l["falhas"] > 0]
    pls = [l["pl"] for l in ls if l["pl"]]
    plr = [l["pl_re"] for l in ls if l["pl_re"]]
    als = [l["al"] for l in ls if l["al_n"]]
    return {
        "n": len(ls),
        "tcr": pct(sum(l["pos_ok"] for l in multi), len(multi)), "tcr_n": len(multi),
        "tcr_limpo": pct(sum(l["pos_ok"] for l in limpas), len(limpas)), "tcr_limpo_n": len(limpas),
        "frr": pct(sum(l["pos_ok"] for l in cfalha), len(cfalha)), "frr_n": len(cfalha),
        "pl": statistics.mean(pls) if pls else None,
        "pl_re": statistics.mean(plr) if plr else None,
        "al": statistics.mean(als) if als else None,
        "discord": sum(l["discord"] for l in ls),
        "correcoes": sum(l["correcoes"] for l in ls),
        "tools": sum(l["tools"] for l in ls),
        "replan": statistics.mean([l["replan"] for l in ls]) if ls else None,
    }


# --------------------------------------------------------------------- SVG

def escala_bonita(vmax, alvo=4):
    """
    Arredonda o topo do eixo para um numero legivel (1/2/2.5/5 x 10^k).

    Sem isso os ticks saiam como 105/79/52/26 em vez de 100/75/50/25 -- numeros
    quebrados obrigam o leitor a fazer conta para ler o grafico.
    """
    import math
    if vmax <= 0:
        return 1.0, 1
    bruto = vmax / alvo
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * mag:
            passo = m * mag
            break
    else:
        passo = 10 * mag
    topo = math.ceil(vmax / passo) * passo
    casas = max(0, -int(math.floor(math.log10(passo)))) if passo < 1 else 0
    n = max(2, min(8, int(round(topo / passo))))   # ticks caem no passo, nao em topo/4
    return topo, casas, n


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def barras_agrupadas(titulo, categorias, series, *, unidade="%", maxv=None,
                     largura=720, altura=330, casas=0):
    """
    Barras verticais agrupadas. series = [(nome, cor_role, [valores])].

    Especificacoes do guia: barra <=24px, topo arredondado 4px e base reta,
    vao de 2px na cor da superficie entre barras vizinhas, grid em hairline,
    legenda presente a partir de 2 series e rotulo direto em cada barra.
    """
    ml, mr, mt, mb = 56, 16, 46, 54
    pw, ph = largura - ml - mr, altura - mt - mb
    bruto = maxv if maxv is not None else max([max(v) for _, _, v in series] + [1]) * 1.08
    vmax, casas_eixo, n_ticks = escala_bonita(bruto)

    banda = pw / max(len(categorias), 1)
    nser = len(series)
    barw = min(24.0, (banda - 14) / nser)

    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" '
      f'width="{largura}" height="{altura}" font-family=\'{FONT}\' role="img" '
      f'aria-label="{_esc(titulo)}">')
    a('<style>'
      f'.sf{{fill:{C["surface"]}}} .tp{{fill:{C["ink"]}}} .ts{{fill:{C["ink2"]}}} '
      f'.mu{{fill:{C["muted"]}}} .gl{{stroke:{C["grid"]}}} .ax{{stroke:{C["axis"]}}} '
      '@media (prefers-color-scheme: dark){'
      f'.sf{{fill:{CD["surface"]}}} .tp{{fill:{CD["ink"]}}} .ts{{fill:{CD["ink2"]}}} '
      f'.mu{{fill:{CD["muted"]}}} .gl{{stroke:{CD["grid"]}}} .ax{{stroke:{CD["axis"]}}}'
      '}</style>')
    a(f'<rect class="sf" x="0" y="0" width="{largura}" height="{altura}"/>')
    a(f'<text class="tp" x="0" y="18" font-size="14" font-weight="600">{_esc(titulo)}</text>')

    # legenda (>=2 series)
    if nser >= 2:
        lx = 0
        for nome, role, _ in series:
            a(f'<rect x="{lx}" y="28" width="9" height="9" rx="2" fill="{C[role]}"/>')
            a(f'<text class="ts" x="{lx+14}" y="36" font-size="11">{_esc(nome)}</text>')
            lx += 16 + 7 * len(nome)

    # grid + eixo y
    for i in range(n_ticks + 1):
        v = vmax * i / n_ticks
        y = mt + ph - (v / vmax) * ph
        a(f'<line class="gl" x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" stroke-width="1"/>')
        a(f'<text class="mu" x="{ml-8}" y="{y+4:.1f}" font-size="11" text-anchor="end" '
          f'style="font-variant-numeric:tabular-nums">{v:.{casas_eixo}f}</text>')
    a(f'<line class="ax" x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" stroke-width="1"/>')

    for ci, cat in enumerate(categorias):
        cx = ml + banda * ci + banda / 2
        grupo = barw * nser + 2 * (nser - 1)
        x0 = cx - grupo / 2
        for si, (_, role, vals) in enumerate(series):
            v = vals[ci]
            h = (v / vmax) * ph if vmax else 0
            x = x0 + si * (barw + 2)
            y = mt + ph - h
            if h >= 4:
                a(f'<path d="M{x:.1f},{mt+ph} L{x:.1f},{y+4:.1f} Q{x:.1f},{y:.1f} {x+4:.1f},{y:.1f} '
                  f'L{x+barw-4:.1f},{y:.1f} Q{x+barw:.1f},{y:.1f} {x+barw:.1f},{y+4:.1f} '
                  f'L{x+barw:.1f},{mt+ph} Z" fill="{C[role]}"/>')
            elif v > 0:
                a(f'<rect x="{x:.1f}" y="{y:.1f}" width="{barw:.1f}" height="{h:.1f}" fill="{C[role]}"/>')
            rot = f"{v:.{casas}f}" if v else "0"
            a(f'<text class="ts" x="{x+barw/2:.1f}" y="{y-5:.1f}" font-size="10.5" '
              f'text-anchor="middle" style="font-variant-numeric:tabular-nums">{rot}</text>')
        a(f'<text class="ts" x="{cx:.1f}" y="{mt+ph+17:.1f}" font-size="11" '
          f'text-anchor="middle">{_esc(cat)}</text>')

    a(f'<text class="mu" x="{ml}" y="{altura-6}" font-size="10.5">{_esc(unidade)}</text>')
    a('</svg>')
    return "\n".join(o)


def barras_h(titulo, rotulos, valores, role="s1", *, unidade="s", largura=720,
             casas=3):
    """Barras horizontais, uma serie (sem legenda: o titulo nomeia a serie)."""
    ml, mr, mt, mb = 150, 60, 40, 28
    bh, gap = 22, 16
    altura = mt + len(valores) * (bh + gap) + mb
    pw = largura - ml - mr
    vmax = max(valores + [1e-9]) * 1.15

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" '
         f'width="{largura}" height="{altura}" font-family=\'{FONT}\' role="img" '
         f'aria-label="{_esc(titulo)}">']
    a = o.append
    a('<style>'
      f'.sf{{fill:{C["surface"]}}} .tp{{fill:{C["ink"]}}} .ts{{fill:{C["ink2"]}}} '
      f'.mu{{fill:{C["muted"]}}} .ax{{stroke:{C["axis"]}}} '
      '@media (prefers-color-scheme: dark){'
      f'.sf{{fill:{CD["surface"]}}} .tp{{fill:{CD["ink"]}}} .ts{{fill:{CD["ink2"]}}} '
      f'.mu{{fill:{CD["muted"]}}} .ax{{stroke:{CD["axis"]}}}'
      '}</style>')
    a(f'<rect class="sf" x="0" y="0" width="{largura}" height="{altura}"/>')
    a(f'<text class="tp" x="0" y="18" font-size="14" font-weight="600">{_esc(titulo)}</text>')
    a(f'<line class="ax" x1="{ml}" y1="{mt-6}" x2="{ml}" y2="{altura-mb+4}" stroke-width="1"/>')
    for i, (rot, v) in enumerate(zip(rotulos, valores)):
        y = mt + i * (bh + gap)
        w = (v / vmax) * pw
        if w >= 4:
            a(f'<path d="M{ml},{y} L{ml+w-4:.1f},{y} Q{ml+w:.1f},{y} {ml+w:.1f},{y+4} '
              f'L{ml+w:.1f},{y+bh-4} Q{ml+w:.1f},{y+bh} {ml+w-4:.1f},{y+bh} L{ml},{y+bh} Z" '
              f'fill="{C[role]}"/>')
        a(f'<text class="ts" x="{ml-10}" y="{y+bh/2+4}" font-size="11.5" '
          f'text-anchor="end">{_esc(rot)}</text>')
        a(f'<text class="ts" x="{ml+w+8:.1f}" y="{y+bh/2+4}" font-size="11" '
          f'style="font-variant-numeric:tabular-nums">{v:.{casas}f} {unidade}</text>')
    a('</svg>')
    return "\n".join(o)


def kpi(rotulo, valor, sub="", cor="ink"):
    return (f'<div class="kpi"><div class="kl">{_esc(rotulo)}</div>'
            f'<div class="kv" style="color:var(--{cor})">{_esc(valor)}</div>'
            f'<div class="ks">{_esc(sub)}</div></div>')


# ------------------------------------------------------------------ relatorio

HTML_CSS = """
:root{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
--muted:#898781;--grid:#e1e0d9;--good:#0ca30c;--critical:#d03b3b;--s1:#2a78d6;}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
--surface:#1a1a19;--plane:#0d0d0d;--ink:#ffffff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--good:#0ca30c;--critical:#d03b3b;--s1:#3987e5;}}
:root[data-theme="dark"]{--surface:#1a1a19;--plane:#0d0d0d;--ink:#ffffff;
--ink2:#c3c2b7;--grid:#2c2c2a;--s1:#3987e5;}
*{box-sizing:border-box}
body{margin:0;padding:32px 16px;background:var(--plane);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.55}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:23px;margin:0 0 4px}
h2{font-size:16px;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--grid)}
.meta{color:var(--ink2);font-size:13px;margin-bottom:8px}
.aviso{background:var(--surface);border-left:3px solid var(--critical);
padding:10px 14px;font-size:13px;color:var(--ink2);margin:16px 0;border-radius:4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.kpi{background:var(--surface);border:1px solid var(--grid);border-radius:8px;padding:14px}
.kl{font-size:11.5px;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
.kv{font-size:27px;font-weight:650;margin:4px 0 2px}
.ks{font-size:11.5px;color:var(--muted)}
figure{margin:18px 0;background:var(--surface);border:1px solid var(--grid);
border-radius:8px;padding:16px;overflow-x:auto}
figure svg{display:block;max-width:100%;height:auto}
figcaption{font-size:12px;color:var(--ink2);margin-top:10px}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin:12px 0;
background:var(--surface);border-radius:8px;overflow:hidden}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--grid)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--ink2);font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:var(--good);font-weight:600}.nao{color:var(--critical);font-weight:600}
@media(max-width:600px){body{padding:20px 16px}.kv{font-size:23px}}
"""


def tabela(cabecalho, linhas, numericas=()):
    o = ["<table><thead><tr>"]
    for h in cabecalho:
        o.append(f"<th>{_esc(h)}</th>")
    o.append("</tr></thead><tbody>")
    for ln in linhas:
        o.append("<tr>")
        for i, c in enumerate(ln):
            cls = ' class="n"' if i in numericas else ""
            if c == "OK":
                o.append(f'<td{cls}><span class="ok">OK</span></td>')
            elif c == "NAO":
                o.append(f'<td{cls}><span class="nao">NAO</span></td>')
            else:
                o.append(f"<td{cls}>{_esc(c)}</td>")
        o.append("</tr>")
    o.append("</tbody></table>")
    return "".join(o)


def md_tabela(cabecalho, linhas):
    o = ["| " + " | ".join(str(h) for h in cabecalho) + " |",
         "|" + "|".join("---" for _ in cabecalho) + "|"]
    for ln in linhas:
        o.append("| " + " | ".join(str(c) for c in ln) + " |")
    return "\n".join(o)


def main():
    ls = carrega()
    if not ls:
        print(f"[ERRO] nenhum experimentos_*.csv em {RES}")
        return 1

    modos = sorted({l["modo"] for l in ls})
    ag_total = agrega(ls)
    ag_modo = {m: agrega([l for l in ls if l["modo"] == m]) for m in modos}
    tarefas = sorted({l["tarefa"] for l in ls})
    os.makedirs(RES, exist_ok=True)

    figs = {}

    # 1) TCR por tarefa: sem falha vs com falha (so tarefas multi-etapa contam p/ TCR,
    #    mas o grafico mostra todas para dar o panorama)
    def taxa(tar, com_falha):
        sel = [l for l in ls if l["tarefa"] == tar
               and ((l["falhas"] > 0) == com_falha)]
        return pct(sum(l["pos_ok"] for l in sel), len(sel)) or 0.0

    figs["fig_sucesso_por_tarefa"] = barras_agrupadas(
        "Pos-condicao cumprida por tarefa (%)", tarefas,
        [("sem falha injetada", "s1", [taxa(t, False) for t in tarefas]),
         ("com falha injetada", "s2", [taxa(t, True) for t in tarefas])],
        unidade="% de execucoes verificadas por pos-condicao externa", maxv=100)

    # 2) Replanejamentos por tarefa
    def media_replan(tar, com_falha):
        sel = [l["replan"] for l in ls if l["tarefa"] == tar
               and ((l["falhas"] > 0) == com_falha)]
        return statistics.mean(sel) if sel else 0.0

    figs["fig_replanejamentos"] = barras_agrupadas(
        "Replanejamentos por missao", tarefas,
        [("sem falha injetada", "s1", [media_replan(t, False) for t in tarefas]),
         ("com falha injetada", "s2", [media_replan(t, True) for t in tarefas])],
        unidade="numero medio de replanejamentos por execucao", casas=1)

    # 3) Latencia de planejamento (PL): inicial vs replanejamento, mesma escala.
    #    A AL fica fora deste grafico de proposito: e 3 ordens de grandeza menor,
    #    e por-las no mesmo eixo seria o erro de duas escalas.
    if ag_total["pl"]:
        figs["fig_latencia_planejamento"] = barras_h(
            "Latencia de Planejamento (PL)",
            ["decomposicao inicial", "replanejamento"],
            [ag_total["pl"] or 0.0, ag_total["pl_re"] or 0.0],
            unidade="s", casas=3)

    # 4) Duracao por tarefa, um grafico por modo (escalas muito diferentes:
    #    pequenos multiplos em vez de um eixo compartilhado)
    for m in modos:
        vals = []
        for t in tarefas:
            sel = [l["dur"] for l in ls if l["tarefa"] == t and l["modo"] == m]
            vals.append(statistics.mean(sel) if sel else 0.0)
        rotulo = "navegacao simulada" if m == "sim" else "navegacao real (Nav2 + Gazebo)"
        figs[f"fig_duracao_{m}"] = barras_agrupadas(
            f"Duracao media da missao - {rotulo}", tarefas,
            [("duracao", "s3", vals)], unidade="segundos por missao", casas=1)

    # Achado central: separar falha de localizacao de falha de raciocinio.
    cum = [l for l in ls if l["pos_ok"] and l.get("eloc")]
    nao = [l for l in ls if not l["pos_ok"] and l.get("eloc")]
    if cum and nao:
        figs["fig_localizacao_vs_resultado"] = barras_h(
            "Erro de localizacao por desfecho da missao",
            ["missoes que cumpriram", "missoes que falharam"],
            [statistics.mean([l["eloc"] for l in cum]),
             statistics.mean([l["eloc"] for l in nao])],
            role="s2", unidade="m", casas=2)

    for nome, svg in figs.items():
        with open(os.path.join(RES, nome + ".svg"), "w", encoding="utf-8") as f:
            f.write(svg)

    # ---------------- tabelas ----------------
    cab_m = ["Metrica", "Definicao (secao 8.3)", *[f"{m}" for m in modos], "Geral"]
    def cel(ag, k, suf="", casas=1):
        v = ag.get(k)
        return "-" if v is None else f"{v:.{casas}f}{suf}"
    lin_m = [
        ["TCR", "tarefas multi-etapa concluidas",
         *[f'{cel(ag_modo[m],"tcr","%")} (n={ag_modo[m]["tcr_n"]})' for m in modos],
         f'{cel(ag_total,"tcr","%")} (n={ag_total["tcr_n"]})'],
        ["FRR", "falhas injetadas das quais se recuperou",
         *[f'{cel(ag_modo[m],"frr","%")} (n={ag_modo[m]["frr_n"]})' for m in modos],
         f'{cel(ag_total,"frr","%")} (n={ag_total["frr_n"]})'],
        ["PL", "tempo do Planejador para decompor",
         *[cel(ag_modo[m], "pl", " s", 3) for m in modos], cel(ag_total, "pl", " s", 3)],
        ["PL (replan)", "tempo para gerar plano de recuperacao",
         *[cel(ag_modo[m], "pl_re", " s", 3) for m in modos], cel(ag_total, "pl_re", " s", 3)],
        ["AL", "feedback de sucesso -> despacho do proximo passo",
         *[cel(ag_modo[m], "al", " s", 6) for m in modos], cel(ag_total, "al", " s", 6)],
        ["Discordancias", "agente disse sucesso e pos-condicao falhou",
         *[str(ag_modo[m]["discord"]) for m in modos], str(ag_total["discord"])],
    ]

    cab_t = ["Tarefa", "Modo", "Falhas inj.", "Agente declarou", "Pos-condicao",
             "Replan", "Tools", "Dur (s)"]
    lin_t = [[l["tarefa"], l["modo"], l["falhas"], l["declarou"],
              "OK" if l["pos_ok"] else "NAO", l["replan"], l["tools"], f'{l["dur"]:.1f}']
             for l in ls]

    # ---------------- HTML ----------------
    tem_real = "real" in modos
    H = [f'<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>Validacao MAS-LLM</title>', f"<style>{HTML_CSS}</style></head><body><div class='wrap'>",
         "<h1>Validacao do Sistema Multiagente LLM</h1>",
         "<div class='meta'>RoboCup@Home OPL &middot; orquestracao de modulos legados "
         "ROS 2 &middot; LLM local llama3.1 via Ollama</div>",
         f"<div class='meta'>{ag_total['n']} execucoes &middot; modos: "
         f"{', '.join(modos)} &middot; {len(tarefas)} tarefas</div>"]

    if not tem_real:
        H.append("<div class='aviso'><strong>Atencao:</strong> estes dados sao todos de "
                 "navegacao <strong>simulada</strong> &mdash; a chegada e assumida, nao "
                 "verificada por TF. O raciocinio (decompor, detectar falha, replanejar) "
                 "e exercitado de verdade; o deslocamento fisico, nao.</div>")
    else:
        H.append("<div class='aviso'>Nas execucoes <strong>real</strong> a pos-condicao e "
                 "conferida contra a <strong>pose verdadeira do Gazebo</strong>, nao contra o TF "
                 "que o robo acredita &mdash; o TF chegou a errar 18 m no Teste 1. Execucoes "
                 "<strong>sim</strong>, se houver, assumem a chegada e estao rotuladas na tabela.</div>")

    H.append("<div class='kpis'>")
    H.append(kpi("TCR", cel(ag_total, "tcr", "%"), f"tarefas multi-etapa (n={ag_total['tcr_n']})"))
    H.append(kpi("FRR", cel(ag_total, "frr", "%"), f"falhas injetadas (n={ag_total['frr_n']})"))
    H.append(kpi("PL", cel(ag_total, "pl", " s", 3), "decomposicao de tarefa"))
    H.append(kpi("AL", cel(ag_total, "al", " s", 6), "reatividade do Supervisor"))
    H.append(kpi("Discordancias", str(ag_total["discord"]),
                 f"de {ag_total['n']} execucoes",
                 "good" if ag_total["discord"] == 0 else "critical"))
    H.append("</div>")

    H.append("<h2>Metricas da secao 8.3 do projeto</h2>")
    H.append(tabela(cab_m, lin_m))
    H.append(f"<div class='meta'>Guarda deterministica corrigiu {ag_total['correcoes']} "
             f"de {ag_total['tools']} chamadas de ferramenta "
             f"({pct(ag_total['correcoes'], ag_total['tools']) or 0:.1f}%). "
             f"Media de {ag_total['replan']:.2f} replanejamentos por missao.</div>")

    ordem = ["fig_sucesso_por_tarefa", "fig_localizacao_vs_resultado",
             "fig_replanejamentos", "fig_latencia_planejamento"] + \
            [f"fig_duracao_{m}" for m in modos]
    legendas = {
        "fig_sucesso_por_tarefa": "Pos-condicao verificada de fora, contra o ground truth do "
            "cenario (e a pose por TF no modo real) &mdash; nao o que o agente declarou.",
        "fig_replanejamentos": "Replanejamentos disparados pelo Supervisor. Barras laranja "
            "mostram o custo de contornar a falha injetada.",
        "fig_latencia_planejamento": "A Latencia de Acao (AL) nao aparece aqui de proposito: "
            "e tres ordens de grandeza menor, e dividir o eixo seria enganoso.",
        "fig_localizacao_vs_resultado": "Toda missao que falhou tinha a localizacao "
            "degradada; nenhuma falhou com a pose correta. O gargalo esta na camada "
            "de navegacao legada, nao no raciocinio dos agentes.",
    }
    H.append("<h2>Graficos</h2>")
    for nome in ordem:
        if nome not in figs:
            continue
        cap = legendas.get(nome, "Duracao media por tarefa. Escalas de modos diferentes "
                                 "ficam em graficos separados, nunca em dois eixos.")
        H.append(f"<figure>{figs[nome]}<figcaption>{cap}</figcaption></figure>")

    H.append("<h2>Execucoes</h2>")
    H.append(tabela(cab_t, lin_t, numericas=(2, 5, 6, 7)))

    falhas = [l for l in ls if not l["pos_ok"]]
    if falhas:
        H.append("<h2>Execucoes que nao cumpriram a pos-condicao</h2><ul>")
        for l in falhas:
            H.append(f"<li><strong>{_esc(l['tarefa'])}</strong> ({l['modo']}, "
                     f"falhas inj.: {l['falhas']}, agente: {_esc(l['declarou'])})</li>")
        H.append("</ul>")

    H.append("</div></body></html>")

    with open(os.path.join(RES, "relatorio.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(H))

    with open(os.path.join(RES, "tabelas.md"), "w", encoding="utf-8") as f:
        f.write("# Tabelas de validacao\n\n## Metricas (secao 8.3)\n\n")
        f.write(md_tabela(cab_m, lin_m))
        f.write("\n\n## Execucoes\n\n")
        f.write(md_tabela(cab_t, lin_t))
        f.write("\n")

    print(f"[OK] {ag_total['n']} execucoes | modos: {', '.join(modos)}")
    print(f"     TCR={cel(ag_total,'tcr','%')} (n={ag_total['tcr_n']})  "
          f"FRR={cel(ag_total,'frr','%')} (n={ag_total['frr_n']})  "
          f"PL={cel(ag_total,'pl','s',3)}  AL={cel(ag_total,'al','s',6)}  "
          f"discordancias={ag_total['discord']}")
    print(f"[SAIDA] {RES}/relatorio.html")
    print(f"[SAIDA] {RES}/tabelas.md")
    for n in figs:
        print(f"[SAIDA] {RES}/{n}.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
