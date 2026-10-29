# Teste 2 — Métricas de validação do sistema multiagente

**Natureza.** 50 execuções no Gazebo real (Cenario1, casa de 30 × 27 m), com os três
agentes em operação e LLM local `llama3.1` via Ollama. Toda pós-condição foi verificada
contra a **pose verdadeira do Gazebo**, nunca contra o TF que o robô acredita.

- 5 tarefas × 2 condições (sem/com falha injetada) × 5 repetições
- Dados brutos: `experimentos_real_20261006_125022.csv` (50 linhas, 23 colunas)

## Métricas da seção 8.3

| Métrica | Valor | n | Definição do pré-projeto |
|---|---|---|---|
| **TCR** | **70%** | 40 | tarefas multi-etapa concluídas sem intervenção humana |
| TCR sem falha injetada | 70% | 20 | mesma métrica, só execuções sem falha induzida |
| **FRR** | **72%** | 25 | falhas introduzidas das quais o Supervisor se recuperou |
| **PL** | **0.779 s** | 50 | tempo do Planejador para decompor a tarefa |
| PL (replanejamento) | 0.863 s | 35 | tempo para gerar plano de recuperação |
| **AL** | **0.0308 s** | 45 | feedback de sucesso → despacho do próximo passo |

## Honestidade do relato

- **Discordâncias: 0 de 50.** Em nenhuma execução o agente declarou
  sucesso com a pós-condição falsa. Era a falha central da arquitetura original.
- Robô tombado: 0 de 50.
- Correções da guarda determinística: 65 em 359 chamadas de ferramenta.

## Onde estão as falhas

Das **15** execuções que não cumpriram a pós-condição:

| Critério | Quantidade |
|---|---|
| com deriva de localização ≥ 1,5 m | **15 de 15 (100%)** |
| com localização correta (< 1,5 m) | 0 de 15 (0%) |
| que esgotaram o teto de replanejamentos | 15 de 15 |

| Erro de localização | Média |
|---|---|
| nas missões que cumpriram | 1.26 m |
| nas missões que falharam | **9.31 m** |

**Nenhuma falha ocorreu com a localização correta.** Em todas as 15, o Planejador
gerou planos válidos e o Supervisor disparou os 6 replanejamentos permitidos antes de
desistir honestamente — o robô é que não sabia onde estava. O gargalo está na camada
de navegação legada, não no módulo de raciocínio proposto.

## Desempenho por tarefa

| Tarefa | Cumpriu | Sem falha | Com falha | Replan médio | Duração média |
|---|---|---|---|---|---|
| T1_nav | 7/10 | 60% | 80% | 2.2 | 115 s |
| T2_pessoa | 6/10 | 40% | 80% | 3.0 | 187 s |
| T3_objeto | 6/10 | 100% | 20% | 2.8 | 214 s |
| T4_entrega | 8/10 | 60% | 100% | 2.1 | 220 s |
| T5_sequencia | 8/10 | 80% | 80% | 1.8 | 221 s |

## Observação sobre o FRR maior que o TCR sem falha

O desempenho com falha injetada (72%) ficou acima do desempenho sem falha (70%),
o que parece contraintuitivo. A explicação está no mecanismo da injeção: a falha bloqueia
a rota **antes** do deslocamento, então o robô replaneja cedo, sem percorrer a travessia
longa que é justamente onde a localização deriva. O número não indica que falhar ajuda —
indica que **o custo está na travessia física**, coerente com o achado da seção anterior.

## Limitações

1. Sem reinício do simulador entre execuções: o reset de mundo do Ignition Fortress não
   restaura poses de modelo, e o teleporte dessincroniza a odometria do scan matching.
   Cada execução reancora a pose por `/initialpose` no setup, e a deriva acumulada
   antes da correção é registrada na coluna `erro_loc_antes_m`.
2. Percepção e manipulação são simuladas contra o ground truth do cenário, pois o
   simulador não tem módulo de visão nem braço. A navegação é real.
3. Amostra de 5 repetições por condição; suficiente para a tendência, não para
   intervalo de confiança estreito.
