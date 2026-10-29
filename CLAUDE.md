# TCC — Sistema Multiagente LLM para RoboCup@Home

Módulo de raciocínio multiagente que orquestra módulos ROS 2 legados, substituindo
o roteador reativo de passo único por Supervisor + Planejador + Executor (LangGraph).

Autor: Lucca Santos Cerasomma / 113653 — Centro Universitário Hermínio Ometto.
Pré-projeto: `MAS/config/Projeto_RoboCup_Home_Multiagente_LLM.txt` (as métricas
exigidas estão na seção 8.3).

## Resultados já coletados

**`MAS/resultados/RESULTADOS_PARA_ARTIGO.md` é o documento consolidado** — ambiente,
arquitetura, toolkit, metodologia, os dois testes, limitações e recomendações de
redação. Comece por ele.

Teste 2 (n=50, Gazebo real): **TCR 70,0% · FRR 72,0% · PL 0,779 s · AL 0,0308 s ·
0 discordâncias**. Das 15 missões que falharam, 15 tinham deriva de localização
≥ 1,5 m e nenhuma falhou com a pose correta — o gargalo é a navegação legada,
não o raciocínio.

## Restrições do projeto

- **LLM 100% local: `llama3.1` 8B via Ollama (Q4_K_M), temperatura 0.** O Gemini foi
  abandonado por custo; `langchain-google-genai` não deve voltar ao caminho de execução.
- **Verificação de resultado nunca usa o TF.** O TF é o que o robô acredita e já errou
  18 m. A pós-condição de cada missão é conferida contra a pose verdadeira do Gazebo
  (`/world/empty/pose/info`), convertida para o frame do mapa pelo offset (-3,9; -5,8).
  Verificar com o TF seria circular.

## Estrutura

```
MAS/
  main.py                  missão única, interativa
  run_experiments.py       campanha de experimentos (TCR/FRR/PL/AL)
  gerar_graficos.py        tabelas + figuras SVG a partir dos CSVs
  src/agents/              ATIVO: supervisor, planner, executor, graph, objetivo
  src/tools/               ATIVO: ros_bridge, robot_tools (10 tools), scenario
  src/core/state.py        COMPARTILHADO: AgentState + MissionMetrics
  src/core/{nodes,tools}.py  dormente: implementação paralela de outra sessão
  legacy_v1/               arquivo histórico da primeira versão
  resultados/              dados, documentos e figuras
ros2_ws_vinicius/          módulo de navegação legado (Nav2, Gazebo, mapas)
ros2_ws_victor/            módulo de PLN legado (RAG, cenários, scenario_manager)
```

A integração com o módulo legado é pelo **tópico ROS 2 `/room`** (consumido por
`navigate_to_goal.py`), com resultado retornando em `/nav_result`. O contrato é o
tópico, não a chamada de função.

## Como rodar

```bash
# 1. Sobe Gazebo + SLAM/AMCL + Nav2 + nó de navegação + Ollama
MAS_AUTOSTART=0 ~/ros2_ws/iniciar_projeto.sh

# 2. Campanha de experimentos
cd ~/ros2_ws/src/multi-agent/MAS
export MAS_GOALS_FILE=../ros2_ws_vinicius/src/robot_bringup/config/goals_casa.json
python3 run_experiments.py --modo real --reps 5

# 3. Tabelas e figuras
python3 gerar_graficos.py
```

Variáveis: `MAS_MODEL` (padrão `llama3.1`), `MAS_MAX_REPLANS` (6), `MAS_FAULT_ROOMS`
(injeção de falha), `MAS_SIM_NAV=1` (navegação simulada, rápida), `MAS_GOALS_FILE`,
`SLAM_MODE` (`localization` padrão / `mapping`).

## Armadilhas já pagas — não repetir

1. **Não teleportar o robô** (`ign service set_pose`). Move o corpo mas não o
   integrador de odometria do DiffDrive; o scan matching não reconcilia e a
   localização morre. Entre execuções, o robô volta à base **navegando**.
2. **O reset de mundo do Ignition Fortress não funciona.** `reset: {all: true}`
   responde `true` e não move nada.
3. **O Gazebo abre pausado.** Sem despausar, o `/clock` não avança e o Nav2 sobe com
   `bt_navigator` e `behavior_server` em `inactive`, rejeitando toda meta em 0,3 s.
   O lançador já despausa por serviço.
4. **`ros2 topic pub --once` é racy** — o publicador morre antes do discovery do DDS.
   Para `/initialpose`, usar `-t 6 -r 1`.
5. **Velocidade alta quebra a localização.** `max_vel_x` está em 0,26 m/s; com 0,5 m/s
   o AMCL perdia o rastro em travessias longas.
6. **Gazebo não sobe de dentro do ambiente de ferramenta do Claude** (crash de GLX /
   Ogre). Quem lança a pilha é o usuário, pelo terminal da sessão gráfica.
