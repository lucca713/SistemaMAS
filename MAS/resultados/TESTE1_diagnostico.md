# Teste 1 — Iteração de diagnóstico da integração física

**Natureza deste teste.** O Teste 1 **não mediu TCR, FRR, PL nem AL.** Ele exercitou
apenas a camada de navegação (ponte ROS 2 ↔ Nav2), sem os agentes Supervisor,
Planejador e Executor. Serve como registro de engenharia: estabelece a linha de
base da integração física e documenta cinco defeitos que teriam contaminado
qualquer métrica coletada antes de corrigi-los.

- 25 execuções de rota, 4 configurações
- Cenário Gazebo: Cenario1 (casa de 30 × 27 m), robô spawnando em (-3,9, -5,8)
- Dados brutos: `teste1_diagnostico.csv`

## Resultado por configuração

| Fase | Configuração | Chegou | Taxa |
|---|---|---|---|
| A | SLAM em modo *mapping* + waypoints deduzidos da geometria do SDF | 2/5 | 40% |
| B | SLAM em modo *mapping* + sondagem empírica por coordenada | 7/10 | 70% |
| C | Nav2 parcialmente ativo (subiu com `/clock` parado) | 1/5 | 20% |
| D | Mapa salvo + modo *localization* + Nav2 ativo | 1/5 | 20% |

A leitura importante não é a taxa, e sim **por que** cada configuração falhou.

## Defeitos encontrados

**1. Waypoints deduzidos de geometria, não medidos.** As coordenadas dos cômodos
foram inferidas lendo as paredes no arquivo SDF. Três dos cinco destinos caíram
fora da área que o SLAM havia mapeado (15,3 × 13,9 m contra os 30 × 27 m da casa),
e o Nav2 abortava em menos de 1 s. *Correção:* carregar o mapa previamente salvo
do Cenario1 (29,1 × 26,1 m), que cobre a casa inteira.

**2. Resultado de navegação atrasado lido como resposta da meta seguinte.** Após
um timeout, a meta pendente não era cancelada no Nav2 e a mensagem tardia em
`/nav_result` era consumida pela navegação seguinte. Quatro destinos "falharam"
em 0,0 s em sequência. *Correção:* casar o resultado com o nome da meta esperada
e publicar cancelamento em `/nav_cancel` ao estourar o timeout.

**3. Nav2 ativando pela metade.** O Gazebo abre pausado; o `/clock` não avança; o
Nav2, configurado com `use_sim_time`, sobe com `bt_navigator` e `behavior_server`
em estado `inactive`. Toda meta é **rejeitada** em ~0,3 s. *Correção:* o lançador
despausa a simulação por serviço e aguarda o tempo simulado antes de subir o Nav2.

**4. Tolerância de chegada apertada demais.** Com `xy_goal_tolerance: 0,25 m` e
`yaw_goal_tolerance: 0,25 rad`, o robô chegou a 2,03 m da sala e ficou oscilando
sem fechar a meta. Ir até um *cômodo* não exige pose exata. *Correção:*
`xy: 0,50 m`, `yaw: 3,14 rad`.

**5. Odometria corrompida — o defeito que invalidou a verificação.** O robô tombou
sobre a mesa amarela (altura real `z = 0,70 m`, quatérnion `(0,70, -0,08, 0,67, 0,22)`)
e as rodas patinaram no vazio. O plugin DiffDrive integra rotação de roda e nunca
zera, acumulando erro permanente. O SLAM usa a odometria como palpite de movimento
e divergiu junto.

Durante a Fase D o erro de localização cresceu de 0,25 m para 18,46 m:

| Destino | Nav2 reportou | Distância real | Erro de localização |
|---|---|---|---|
| living room | chegou (0,48 m) | **0,72 m** ✔ | 0,25 m |
| kitchen | chegou (0,50 m) | **7,45 m** ✘ | 7,00 m |
| bedroom | chegou (0,49 m) | **4,18 m** ✘ | 3,77 m |
| dining room | timeout | **28,09 m** ✘ | 17,86 m |
| hall | chegou | **19,22 m** ✘ | 18,46 m |

Em dado momento o TF reportava `(-0,65, 0,61)` com o robô fisicamente em
`(-8,08, -7,12)` — 7,5 m de discrepância.

*Correção metodológica:* separar os papéis. O **agente** decide usando o TF (o que
o robô acredita, como teria num robô real); o **verificador do experimento** confere
com a pose verdadeira do Gazebo, convertida para o frame do mapa pelo deslocamento
medido de (-3,9, -5,8). A diferença entre as duas passa a ser registrada como
métrica de erro de localização.

Sem essa separação, a Fase D teria sido reportada como **3 de 5 destinos alcançados**,
quando apenas **1** foi de fato alcançado.

## Mudanças levadas para o Teste 2

| Dimensão | Teste 1 | Teste 2 |
|---|---|---|
| Mapa | levantado ao vivo (SLAM *mapping*) | mapa salvo do Cenario1, modo *localization* |
| Waypoints | deduzidos do SDF | validados contra o mapa salvo |
| Verificação de chegada | TF `map→base_link` | pose verdadeira do Gazebo |
| Ativação do Nav2 | sujeita ao Gazebo pausado | despausa automática + espera do `/clock` |
| Tolerância de meta | 0,25 m / 0,25 rad | 0,50 m / 3,14 rad |
| Timeout de navegação | deixava meta pendurada | cancela via `/nav_cancel` |
| Queda do robô | não detectada | coluna `robo_tombado` (`z > 0,55 m`) |
| Erro de localização | não medido | coluna `erro_localizacao_m` |

## Limitação assumida

O Teste 1 foi conduzido com teleporte do robô entre tentativas, o que agravou a
dessincronização entre odometria e pose real. O Teste 2 **não usa teleporte**: o
retorno à base é feito por navegação, como seria num robô real.
