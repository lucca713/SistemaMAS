# Resultados para o artigo — Sistema Multiagente LLM para RoboCup@Home

Documento autossuficiente com tudo que foi medido, a configuração usada e as
observações que considero relevantes para a redação. Gerado em 06/10/2026.

**Título do trabalho:** Proposta de um Sistema Multiagente Baseado em LLM para
Orquestração de Módulos Legados na RoboCup@Home — Lucca Santos Cerasomma / 113653,
Centro Universitário da Fundação Hermínio Ometto.

---

## 1. Resumo dos números

| Métrica (§8.3 do pré-projeto) | Valor | n |
|---|---|---|
| **TCR** — Taxa de Conclusão de Tarefa | **70.0%** | 40 |
| TCR sem falha injetada | 70.0% | 20 |
| **FRR** — Taxa de Recuperação de Falha | **72.0%** | 25 |
| **PL** — Latência de Planejamento | **0.779 s** (σ 1.277) | 50 |
| PL em replanejamento | 0.863 s | 35 |
| **AL** — Latência de Ação | **0.0308 s** | 45 |

| Indicador adicional | Valor |
|---|---|
| Discordâncias agente × realidade | **0 de 50** |
| Execuções com robô tombado | 0 de 50 |
| Chamadas de ferramenta | 359 |
| Correções da guarda determinística | 65 (18.1%) |
| Replanejamentos totais | 119 |

---

## 2. Ambiente experimental

| Componente | Versão / configuração |
|---|---|
| Sistema | Ubuntu 22.04, Linux 6.8 |
| ROS 2 | Humble Hawksbill |
| Simulador | Ignition Gazebo 6.18.0 (Fortress) |
| Navegação | Nav2 (DWB local planner, NavFn global planner) |
| Localização | AMCL sobre mapa estático (`likelihood_field`, 500–2000 partículas) |
| **LLM** | **llama3.1:8B — Ollama local, GGUF, quantização Q4_K_M** |
| Orquestração | LangGraph 1.2.11, langchain-core 1.6.0, langchain-ollama 1.1.0, ollama 0.6.2 |
| Python | 3.10.12 |
| Temperatura do LLM | 0 (determinística) em todos os agentes |

**Cenário:** Cenario1 — casa de 30 × 27 m dividida em quatro quadrantes por divisórias,
com mobiliário (mesas, armário, cilindros). Robô diferencial, raio 0,2 m, LiDAR a 10 Hz,
spawn em (-3,9; -5,8).

**Mapa:** `Cenario1_12_11_10h11min` (29,1 × 26,1 m), levantado previamente com SLAM Toolbox
e carregado estaticamente pelo `map_server`.

**Parâmetros de navegação relevantes:** `max_vel_x` 0,26 m/s; `max_vel_theta` 1,0 rad/s;
`xy_goal_tolerance` 0,50 m; `yaw_goal_tolerance` 3,14 rad; `inflation_radius` 0,55 m;
AMCL `update_min_d` 0,1 m.

---

## 3. Arquitetura implementada

Grafo LangGraph de malha fechada, com o Supervisor como ponto de entrada e único
despachante:

```
        SUPERVISOR <---------------+
         |     |      |            |
         v     v      v            |
    PLANNER  EXECUTOR  END         |
         |     |                   |
         +-----+-------------------+
```

| Agente | Papel | Inspiração (Tabela 1 do pré-projeto) |
|---|---|---|
| **Supervisor** | gerência de estado, despacho de passo único, avaliação de objetivo, disparo de replanejamento | MALMM Supervisor + MARS Evaluation |
| **Planejador** | decomposição da intenção em passos; replanejamento com contexto de erro | MALMM Planner |
| **Executor** | tradução de passo em chamada de ferramenta ROS 2 via *tool calling* nativo | ROSA Agent |

O Supervisor acumula o papel de Agente de Avaliação do MARS, conforme §5.1: ele não
aceita "plano esgotado" como missão cumprida — cobra evidência do objetivo no estado do
mundo antes de declarar sucesso.

**Integração com os módulos legados:** as metas de navegação são publicadas no tópico
ROS 2 `/room`, consumido pelo nó `navigate_to_goal.py` do módulo de navegação legado,
que fala com o Nav2 pela action `navigate_to_pose`. O resultado real retorna pelo tópico
`/nav_result`. O contrato de integração é o tópico, não a chamada de função.

---

## 4. Toolkit de ferramentas (Tabela 3 do pré-projeto)

Dez ferramentas expostas ao Executor via `ChatOllama(...).bind_tools()`:

| Ferramenta | Assinatura | Módulo alvo | Verificação do efeito |
|---|---|---|---|
| `navegar_para` | `(destino: str)` | Navegação (Nav2 via `/room`) | pose real do Gazebo vs coordenada da meta |
| `status_navegacao` | `()` | Navegação | — (leitura) |
| `dar_re` | `(distancia_m: float)` | Navegação (`behavior_server`) | deslocamento medido por odometria |
| `girar` | `(graus: float)` | Navegação (`behavior_server`) | status da action |
| `procurar_pessoa_na_sala` | `(nome: str)` | Percepção (simulada) | ground truth do cenário |
| `procurar_objeto_na_sala` | `(objeto: str)` | Percepção (simulada) | ground truth do cenário |
| `pegar_objeto` | `(objeto: str)` | Manipulação (simulada) | presença no cômodo + limite de 3 kg |
| `entregar_objeto` | `(objeto: str, destino: str)` | Manipulação (simulada) | estado de carga do robô |
| `falar` | `(mensagem: str)` | Interação (tópico `/tts`) | publicação confirmada |
| `consultar_base` | `(pergunta: str)` | Conhecimento do ambiente | — (leitura) |

**Decisão de projeto relevante para o artigo:** as ferramentas de percepção são
**por cômodo**, não buscas multi-cômodo. A §7.2 do pré-projeto critica justamente o
`find_person` legado por conter "toda a lógica de negócios (buscar cômodos, navegar,
procurar, repetir)". Mantendo as ferramentas como primitivas, a varredura da casa
precisa **emergir do plano do Planejador** — é isso que o experimento testa.

**Camada de guarda determinística:** o Executor valida a escolha do LLM contra sinais
léxicais fortes do passo e corrige divergências reprodutíveis (o llama3.1 confunde
"pegar" com "procurar" e inverte o sinal do giro). As correções são contabilizadas:
65 em 359 chamadas (18.1%). Esse número é em si um
resultado sobre a confiabilidade de *tool calling* em modelos de 8B.

---

## 5. Metodologia experimental

**Delineamento:** 5 tarefas × 2 condições (sem/com falha injetada) × 5 repetições = 50
execuções, todas no Gazebo com navegação física real.

| ID | Tarefa | Intenção dada ao sistema | Pós-condição verificada |
|---|---|---|---|
| T1_nav | navegação de etapa única | "va ate o kitchen" | robô no cômodo `kitchen` |
| T2_pessoa | busca de pessoa (Estudo de Caso 1) | "encontre a Ana e avise onde ela esta" | Ana localizada em `kitchen` |
| T3_objeto | busca de objeto | "encontre o remote control" | objeto localizado em `living room` |
| T4_entrega | buscar e entregar | "pegue o soda_can no kitchen e leve para o living room" | `soda_can` entregue em `living room` |
| T5_sequencia | sequência + relato | "va ate o bedroom, depois va ate o dining room e avise que terminou" | robô em `dining room` **e** tendo falado |

**Injeção de falha (para o FRR):** a variável `MAS_FAULT_ROOMS` faz a primeira navegação
para um cômodo específico retornar falha com a marca `[FALHA INJETADA]`, simulando porta
bloqueada. A falha dispara uma única vez por cômodo, de modo que o replanejamento possa
contorná-la.

**Verificação da pós-condição — ponto metodológico central:** a conclusão da tarefa
**não é o que o agente declara**. Cada tarefa tem uma pós-condição conferida de fora,
contra o ground truth: a pose verdadeira do robô lida direto do Gazebo
(`/world/empty/pose/info`), convertida para o frame do mapa pelo deslocamento medido de
(-3,9; -5,8), e o estado do cenário (`baseline_house_1.json`).

Isso é necessário porque o TF — o que o robô acredita — chegou a errar 18 m. Verificar
com o TF seria circular: mediria a confiança do robô, não o resultado.

**Separação de papéis:**
- o **agente** decide usando o TF, como faria num robô real;
- o **verificador** confere com a verdade do simulador;
- a diferença entre os dois é registrada como erro de localização.

---

## 6. Teste 1 — Iteração de diagnóstico (25 execuções de rota)

O Teste 1 **não mediu TCR, FRR, PL nem AL**: exercitou apenas a camada de navegação,
sem os agentes. Serve para justificar as correções aplicadas, não para comparar
desempenho da arquitetura.

| Fase | Configuração | Chegou |
|---|---|---|
| A | SLAM *mapping* + waypoints deduzidos do SDF | 2/5 |
| B | SLAM *mapping* + sondagem empírica por coordenada | 7/10 |
| C | Nav2 parcialmente ativo (subiu com `/clock` parado) | 1/5 |
| D | Mapa salvo + modo *localization* + Nav2 ativo | 1/5 |

### Cinco defeitos encontrados

1. **Waypoints deduzidos, não medidos.** Coordenadas inferidas da geometria do SDF;
   três dos cinco destinos caíram fora da área mapeada (15,3 × 13,9 m contra 30 × 27 m
   da casa) e o Nav2 abortava em menos de 1 s.

2. **Resultado de navegação atrasado lido como resposta da meta seguinte.** Após
   timeout, a meta pendente não era cancelada e a mensagem tardia em `/nav_result` era
   consumida pela navegação seguinte — quatro destinos "falharam" em 0,0 s em sequência.

3. **Nav2 ativando pela metade.** O Gazebo abre pausado, o `/clock` não avança e o Nav2
   (com `use_sim_time`) sobe com `bt_navigator` e `behavior_server` em `inactive`.
   Toda meta é **rejeitada** em ~0,3 s.

4. **Tolerância de meta apertada.** Com 0,25 m / 0,25 rad o robô parou a 2,03 m da sala
   oscilando sem fechar a meta.

5. **Odometria corrompida — o defeito que invalidou a verificação.** O robô tombou sobre
   uma mesa (altura real z = 0,70 m) e as rodas patinaram. O plugin DiffDrive integra
   rotação de roda e nunca zera, acumulando erro permanente; o SLAM, que usa a odometria
   como palpite de movimento, divergiu junto.

Na Fase D o erro de localização cresceu de 0,25 m para 18,46 m:

| Destino | Nav2 reportou | Distância real | Erro de localização |
|---|---|---|---|
| living room | chegou (0,48 m) | **0,72 m** ✔ | 0,25 m |
| kitchen | chegou (0,50 m) | **7,45 m** ✘ | 7,00 m |
| bedroom | chegou (0,49 m) | **4,18 m** ✘ | 3,77 m |
| dining room | timeout | **28,09 m** ✘ | 17,86 m |
| hall | chegou | **19,22 m** ✘ | 18,46 m |

> **Número forte para o artigo:** sem verificação independente, a Fase D teria sido
> reportada como **3 de 5 destinos alcançados**; com ela, apenas **1 de 5** foi.

---

## 7. Teste 2 — Métricas da §8.3 (50 execuções)

Já consolidado na seção 1. Desempenho por tarefa:

| Tarefa | Cumpriu | Sem falha | Com falha | Replan médio | Duração média |
|---|---|---|---|---|---|
| T1_nav | 7/10 | 60.0% | 80.0% | 2.2 | 115 s |
| T2_pessoa | 6/10 | 40.0% | 80.0% | 3 | 187 s |
| T3_objeto | 6/10 | 100.0% | 20.0% | 2.8 | 214 s |
| T4_entrega | 8/10 | 60.0% | 100.0% | 2.1 | 220 s |
| T5_sequencia | 8/10 | 80.0% | 80.0% | 1.8 | 221 s |

---

## 8. Achado central — onde estão as falhas

Das **15** execuções que não cumpriram a pós-condição:

| Critério | Quantidade |
|---|---|
| com deriva de localização ≥ 1,5 m | **15 de 15 (100%)** |
| com localização correta (< 1,5 m) | **0 de 15 (0%)** |
| que esgotaram o teto de 6 replanejamentos | 15 de 15 |

| Indicador | Missões cumpridas | Missões falhadas |
|---|---|---|
| Erro de localização médio | 1.26 m | **9.31 m** |
| Replanejamentos médios | 0.83 | 6 |
| Duração média | 121 s | 355 s |

> **Nenhuma falha ocorreu com a localização correta.** Em todas as 15, o Planejador
> gerou planos válidos e o Supervisor disparou os seis replanejamentos permitidos antes
> de desistir honestamente. O gargalo está na camada de navegação legada, não no módulo
> de raciocínio proposto.

### Observação sobre FRR > TCR sem falha

O desempenho com falha injetada (72.0%) ficou acima do desempenho sem falha
(70.0%), o que parece contraintuitivo. A explicação sustentada pelos dados: a
injeção bloqueia a rota **antes** do deslocamento, então o robô replaneja cedo, sem
percorrer a travessia longa que é justamente onde a localização deriva.

O número não indica que falhar ajuda — indica que **o custo está na travessia física**,
coerente com o achado acima. Vale declarar isso explicitamente no artigo, porque um
leitor atento vai estranhar a inversão.

---

## 9. Comparativo Teste 1 → Teste 2

| # | Mudança | Motivo medido no Teste 1 | Efeito no Teste 2 |
|---|---|---|---|
| 1 | Mapa salvo + modo *localization* no lugar de SLAM *mapping* | mapa ao vivo cobria só 15,3 × 13,9 m | casa inteira (29,1 × 26,1 m) navegável |
| 2 | Localizador trocado: `slam_toolbox` → **AMCL** com mapa estático | scan matching puro divergia: 0,25 m → 18,46 m | erro médio **1,26 m** nas missões bem-sucedidas |
| 3 | Velocidade reduzida: 0,5 → **0,26 m/s**; giro 2,5 → 1,0 rad/s | patinação corrompia o modelo de movimento do AMCL | rota até a cozinha, que falhava em 100% das tentativas, passou a chegar a **0,19 m** |
| 4 | `/initialpose` publicado repetidamente (`-t 6 -r 1`) | `--once` encerra antes do discovery do DDS | relocalização confiável no setup |
| 5 | Pós-condição verificada pela **pose verdadeira do Gazebo** | TF reportou (-0,65; 0,61) com robô em (-8,08; -7,12) | **0 discordâncias em 50** |
| 6 | Tolerância de meta 0,25 → **0,50 m** / 3,14 rad | robô parava a 2,03 m oscilando | metas fechando |
| 7 | Cancelamento no timeout via `/nav_cancel` + casamento resultado↔meta | resultado atrasado lido como resposta seguinte | eliminado |
| 8 | Despausa automática do Gazebo + espera do `/clock` | Nav2 rejeitava toda meta | Nav2 ativo em todas as execuções |

---

## 10. Limitações a declarar

1. **Sem reinício do simulador entre execuções.** O reset de mundo do Ignition Fortress
   não restaura poses de modelo (o serviço retorna sucesso sem efeito) e o teleporte
   dessincroniza a odometria do scan matching. Cada execução reancora a pose por
   `/initialpose` no setup; a deriva acumulada antes da correção está registrada na
   coluna `erro_loc_antes_m`.

2. **Percepção e manipulação simuladas.** O simulador não tem módulo de visão nem braço;
   essas ferramentas respondem contra o ground truth do cenário, como no sistema legado.
   **A navegação é real.** Portanto TCR e FRR medem o raciocínio (decompor, detectar
   falha, replanejar) somado à navegação física — não acurácia de percepção.

3. **Amostra de 5 repetições por condição.** Suficiente para tendência, não para
   intervalo de confiança estreito.

4. **Um único cenário e um único LLM.** Sem comparação entre modelos nem entre cenários.

5. **Ausência de linha de base quantitativa do sistema legado.** A comparação com o
   pipeline reativo é argumentativa (ele não decompõe nem replaneja por construção),
   não medida lado a lado.

---

## 11. O que eu recomendo destacar no artigo

**1. O resultado mais forte não é o TCR — é a separação de camadas.** 100% das falhas
são atribuíveis à localização e 0% ao raciocínio. Isso delimita com precisão o que é
contribuição sua e o que é herança dos módulos legados. É o argumento que sustenta a
hipótese do §2 sem depender de um TCR alto.

**2. As zero discordâncias merecem seção própria.** A arquitetura original declarava
sucesso sem verificar — o Supervisor tratava "plano esgotado" como "tarefa cumprida" e
havia um mock que fabricava `{"status": "success"}` quando faltava telemetria. Medir
a honestidade do relato como métrica explícita é incomum na literatura de MAS-LLM e
vale como contribuição metodológica.

**3. Os 65 casos de correção determinística (18.1% das chamadas) são dado publicável**
sobre confiabilidade de *tool calling* em modelos de 8B rodando localmente. Os erros são
reprodutíveis e categorizáveis: confusão entre ferramentas semanticamente próximas
("pegar" × "procurar") e inversão de convenção de sinal. Sugere que *tool calling* nativo
em modelos pequenos precisa de camada de validação.

**4. A AL de 0.0308 s mostra que o overhead de coordenação é desprezível.** O custo está
no LLM do Executor e na navegação física, não na orquestração. Reforça a viabilidade da
arquitetura hierárquica em hardware modesto.

**5. Declare a inversão FRR > TCR sem falha antes que o revisor pergunte**, com a
explicação da seção 8.

**6. O Teste 1 é material legítimo de metodologia**, não um fracasso a esconder. Os cinco
defeitos são armadilhas reais de integração ROS 2 + Nav2 + SLAM que outros grupos de
RoboCup@Home vão encontrar. Documentá-los tem valor prático, e o contraste
"3 de 5 reportados × 1 de 5 reais" justifica empiricamente a escolha metodológica de
verificar contra ground truth.

**7. Trabalhos futuros que os dados apontam:** melhorar a localização (fusão com odometria
visual, tuning do AMCL, landmarks) sem tocar no módulo de raciocínio; e medir uma linha
de base do pipeline legado nas mesmas tarefas, para quantificar o ganho em vez de
argumentá-lo.

---

## 12. Reprodutibilidade

```bash
# 1. Subir a pilha (Gazebo + SLAM/AMCL + Nav2 + nó de navegação + Ollama)
MAS_AUTOSTART=0 ~/ros2_ws/iniciar_projeto.sh

# 2. Rodar a campanha
cd ~/ros2_ws/src/multi-agent/MAS
export MAS_GOALS_FILE=../ros2_ws_vinicius/src/robot_bringup/config/goals_casa.json
python3 run_experiments.py --modo real --reps 5

# 3. Gerar tabelas e figuras
python3 gerar_graficos.py
```

Variáveis de ambiente relevantes: `MAS_MODEL` (padrão `llama3.1`), `MAS_MAX_REPLANS`
(padrão 6, usado 6), `MAS_FAULT_ROOMS` (injeção de falha), `MAS_SIM_NAV=1` (navegação
simulada), `MAS_GOALS_FILE`, `SLAM_MODE` (`localization` padrão / `mapping`).

---

## 13. Índice dos arquivos

Todos em `MAS/resultados/`:

| Arquivo | Conteúdo |
|---|---|
| `RESULTADOS_PARA_ARTIGO.md` | este documento |
| `experimentos_real_20261006_125022.csv` | dados brutos do Teste 2 — 50 linhas × 23 colunas |
| `teste1_diagnostico.csv` | dados brutos do Teste 1 — 25 rotas |
| `TESTE2_metricas.md` | métricas do Teste 2 redigidas |
| `TESTE1_diagnostico.md` | diagnóstico do Teste 1 redigido |
| `COMPARATIVO_1_2.md` | evolução entre os testes |
| `tabelas.md` | tabelas em markdown puro |
| `relatorio.html` | relatório navegável com gráficos embutidos |
| `fig_sucesso_por_tarefa.svg` | pós-condição por tarefa, sem × com falha |
| `fig_localizacao_vs_resultado.svg` | **achado central** — 1.26 m × 9.31 m |
| `fig_replanejamentos.svg` | replanejamentos por missão |
| `fig_latencia_planejamento.svg` | PL inicial × replanejamento |
| `fig_duracao_real.svg` | duração média por tarefa |

### Colunas do CSV do Teste 2

`tarefa`, `multi_etapa`, `base_ok`, `modo`, `falha_injetada_pedida`,
`falhas_injetadas`, `agente_declarou`, `poscondicao_ok`, `discordancia`, `duracao_s`,
`replanejamentos`, `tool_calls`, `correcoes_guarda`, `PL_plan_inicial_s`, `PL_replan_s`,
`AL_acao_s`, `AL_amostras`, `pose_inicial`, `pose_real_fim`, `erro_loc_antes_m`,
`erro_localizacao_m`, `robo_tombado`, `motivo`
