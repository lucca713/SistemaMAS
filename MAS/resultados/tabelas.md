# Tabelas de validacao

## Metricas (secao 8.3)

| Metrica | Definicao (secao 8.3) | real | Geral |
|---|---|---|---|
| TCR | tarefas multi-etapa concluidas | 70.0% (n=40) | 70.0% (n=40) |
| FRR | falhas injetadas das quais se recuperou | 72.0% (n=25) | 72.0% (n=25) |
| PL | tempo do Planejador para decompor | 0.779 s | 0.779 s |
| PL (replan) | tempo para gerar plano de recuperacao | 0.863 s | 0.863 s |
| AL | feedback de sucesso -> despacho do proximo passo | 0.030806 s | 0.030806 s |
| Discordancias | agente disse sucesso e pos-condicao falhou | 0 | 0 |

## Execucoes

| Tarefa | Modo | Falhas inj. | Agente declarou | Pos-condicao | Replan | Tools | Dur (s) |
|---|---|---|---|---|---|---|---|
| T1_nav | real | 0 | failed | NAO | 6 | 12 | 422.6 |
| T1_nav | real | 1 | failed | NAO | 6 | 19 | 394.8 |
| T2_pessoa | real | 0 | success | OK | 0 | 3 | 65.3 |
| T2_pessoa | real | 1 | success | OK | 1 | 6 | 29.9 |
| T3_objeto | real | 0 | success | OK | 0 | 2 | 62.7 |
| T3_objeto | real | 1 | success | OK | 4 | 9 | 353.9 |
| T4_entrega | real | 0 | failed | NAO | 6 | 16 | 442.4 |
| T4_entrega | real | 1 | success | OK | 1 | 7 | 99.3 |
| T5_sequencia | real | 0 | failed | NAO | 6 | 17 | 256.2 |
| T5_sequencia | real | 1 | success | OK | 1 | 6 | 131.0 |
| T1_nav | real | 0 | success | OK | 0 | 1 | 46.6 |
| T1_nav | real | 1 | success | OK | 1 | 4 | 24.6 |
| T2_pessoa | real | 0 | failed | NAO | 6 | 7 | 274.1 |
| T2_pessoa | real | 1 | success | OK | 2 | 10 | 204.1 |
| T3_objeto | real | 0 | success | OK | 0 | 2 | 52.0 |
| T3_objeto | real | 1 | failed | NAO | 6 | 8 | 189.6 |
| T4_entrega | real | 0 | failed | NAO | 6 | 15 | 475.8 |
| T4_entrega | real | 1 | success | OK | 4 | 16 | 298.2 |
| T5_sequencia | real | 0 | success | OK | 0 | 3 | 161.9 |
| T5_sequencia | real | 1 | success | OK | 1 | 6 | 164.7 |
| T1_nav | real | 0 | success | OK | 0 | 1 | 46.4 |
| T1_nav | real | 1 | success | OK | 1 | 4 | 26.1 |
| T2_pessoa | real | 0 | success | OK | 0 | 3 | 33.0 |
| T2_pessoa | real | 1 | success | OK | 1 | 6 | 40.5 |
| T3_objeto | real | 0 | success | OK | 0 | 2 | 57.5 |
| T3_objeto | real | 1 | failed | NAO | 6 | 9 | 421.3 |
| T4_entrega | real | 0 | success | OK | 0 | 4 | 85.3 |
| T4_entrega | real | 1 | success | OK | 1 | 7 | 134.2 |
| T5_sequencia | real | 0 | success | OK | 1 | 7 | 236.3 |
| T5_sequencia | real | 1 | failed | NAO | 6 | 16 | 449.2 |
| T1_nav | real | 0 | failed | NAO | 6 | 7 | 68.7 |
| T1_nav | real | 1 | success | OK | 1 | 4 | 34.8 |
| T2_pessoa | real | 0 | failed | NAO | 6 | 11 | 333.2 |
| T2_pessoa | real | 1 | failed | NAO | 6 | 11 | 336.4 |
| T3_objeto | real | 0 | success | OK | 0 | 2 | 49.4 |
| T3_objeto | real | 1 | failed | NAO | 6 | 9 | 452.2 |
| T4_entrega | real | 0 | success | OK | 0 | 4 | 160.9 |
| T4_entrega | real | 1 | success | OK | 1 | 7 | 137.1 |
| T5_sequencia | real | 0 | success | OK | 0 | 3 | 155.3 |
| T5_sequencia | real | 1 | success | OK | 1 | 6 | 163.2 |
| T1_nav | real | 0 | success | OK | 0 | 1 | 46.5 |
| T1_nav | real | 1 | success | OK | 1 | 4 | 42.8 |
| T2_pessoa | real | 0 | failed | NAO | 6 | 12 | 391.8 |
| T2_pessoa | real | 1 | success | OK | 2 | 10 | 159.9 |
| T3_objeto | real | 0 | success | OK | 0 | 2 | 83.5 |
| T3_objeto | real | 1 | failed | NAO | 6 | 11 | 422.0 |
| T4_entrega | real | 0 | success | OK | 0 | 4 | 127.7 |
| T4_entrega | real | 1 | success | OK | 2 | 10 | 236.4 |
| T5_sequencia | real | 0 | success | OK | 1 | 7 | 314.4 |
| T5_sequencia | real | 1 | success | OK | 1 | 6 | 179.8 |
