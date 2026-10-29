# Sistema Multiagente LLM para Orquestração de Módulos Legados na RoboCup@Home

Módulo de raciocínio multiagente que substitui o roteador reativo de passo único
por três agentes especializados em malha fechada — **Supervisor**, **Planejador**
e **Executor** — orquestrados em LangGraph sobre ROS 2 Humble e Nav2.

**Autor:** Lucca Santos Cerasomma / 113653 — Centro Universitário da Fundação
Hermínio Ometto (FHO).

O problema atacado: o pipeline legado executa uma ação por comando e trava diante
de uma falha de navegação, exigindo reinício manual. A arquitetura proposta detecta
a falha pela telemetria do ROS 2, replaneja em tempo de execução e só declara
sucesso com evidência no estado do mundo.

## Resultados

Campanha de **50 execuções no Gazebo com navegação física real** (5 tarefas × 2
condições × 5 repetições):

| Métrica | Valor |
|---|---|
| TCR — Taxa de Conclusão de Tarefa | 70,0 % |
| FRR — Taxa de Recuperação de Falha | 72,0 % |
| PL — Latência de Planejamento | 0,779 s |
| AL — Latência de Ação | 0,0308 s |
| Discordâncias agente × realidade | **0 de 50** |

Achado central: das 15 missões que não cumpriram a pós-condição, **15 tinham deriva
de localização ≥ 1,5 m e nenhuma falhou com a pose correta**. O gargalo está na
camada de navegação legada, não no módulo de raciocínio proposto.

Documento consolidado: [`MAS/resultados/RESULTADOS_PARA_ARTIGO.md`](MAS/resultados/RESULTADOS_PARA_ARTIGO.md)
— ambiente, arquitetura, toolkit, metodologia, os dois testes e limitações.

## Procedência dos módulos

Este repositório reúne o trabalho de três integrantes para que um único clone
reproduza os experimentos. A autoria de cada parte:

| Diretório | Módulo | Autoria |
|---|---|---|
| `MAS/` | Raciocínio multiagente (contribuição deste TCC) | Lucca Cerasomma |
| `ros2_ws_vinicius/` | Navegação, SLAM, mapas e lançamento do Gazebo | Vinicius |
| `ros2_ws_victor/robot-agent/` | PLN, roteador legado, RAG e cenários | Victor Fiorio Casarin |

O módulo de PLN tem repositório próprio em
`github.com/VictorFiorioCasarin/robot-agent`; a versão aqui parte do commit
`151cca3` e inclui adaptações necessárias à integração com o módulo de raciocínio
(principalmente em `robot_tools.py` e `rag_pipeline.py`).

## Arquitetura

```
        SUPERVISOR <--------------+
         |     |      |           |
         v     v      v           |
    PLANNER  EXECUTOR  END        |
         |     |                  |
         +-----+------------------+
```

O Supervisor é o ponto de entrada e único despachante: avalia a telemetria, despacha
um passo por vez ao Executor, intercepta falhas e aciona o Planejador. O Executor
traduz o passo em chamada de ferramenta por *tool calling* nativo, sem gerar código
ROS 2. A integração com os módulos legados é por tópico (`/room`, `/nav_result`),
não por chamada de função.

## Reprodutibilidade

```bash
# 1. Subir a pilha (Gazebo + AMCL + Nav2 + nó de navegação + Ollama)
MAS_AUTOSTART=0 ./iniciar_projeto.sh

# 2. Rodar a campanha de experimentos
cd MAS
export MAS_GOALS_FILE=../ros2_ws_vinicius/src/robot_bringup/config/goals_casa.json
python3 run_experiments.py --modo real --reps 5

# 3. Gerar tabelas e figuras
python3 gerar_graficos.py

# Missão única e interativa
python3 main.py "va ate o kitchen"
```

**Ambiente:** Ubuntu 22.04 · ROS 2 Humble · Ignition Gazebo 6.18 (Fortress) · Nav2 ·
Python 3.10 · LangGraph 1.2.11 · `llama3.1` 8B (Q4_K_M) via Ollama, temperatura 0.

**LLM 100 % local.** Não há dependência de API paga: a chave em `MAS/config/.env`
(não versionada) é resquício de uma avaliação inicial com Gemini, abandonada por custo.

Variáveis relevantes: `MAS_MODEL`, `MAS_MAX_REPLANS` (padrão 6), `MAS_FAULT_ROOMS`
(injeção de falha para a FRR), `MAS_SIM_NAV=1` (navegação simulada),
`MAS_GOALS_FILE`, `SLAM_MODE`.

## Notas

- Os arquivos `.posegraph` e `.data` do SLAM Toolbox (~83 MB) não são versionados:
  são regeneráveis e o `map_server` precisa apenas do `.pgm` + `.yaml`, que estão aqui.
- `CLAUDE.md` traz o contexto de desenvolvimento e as armadilhas de integração
  ROS 2 + Nav2 + SLAM encontradas no caminho.
