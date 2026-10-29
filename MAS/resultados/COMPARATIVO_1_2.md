# Comparativo Teste 1 → Teste 2

Documento de evolução para a seção de Resultados: o que mudou entre as duas
campanhas, por que mudou, e o efeito medido.

## Os dois testes não medem a mesma coisa

| | Teste 1 | Teste 2 |
|---|---|---|
| Natureza | diagnóstico da integração física | métricas da arquitetura |
| Camada exercitada | ponte ROS 2 ↔ Nav2 | três agentes + toolkit + Nav2 |
| Execuções | 25 rotas | 50 missões |
| Métricas §8.3 | não coletadas | TCR, FRR, PL, AL |

O Teste 1 não produziu TCR nem FRR porque não rodou os agentes. Ele serve para
justificar as correções, não para comparar desempenho do sistema multiagente.

## Mudanças aplicadas e efeito medido

| # | Mudança | Motivo (medido no Teste 1) | Efeito no Teste 2 |
|---|---|---|---|
| 1 | Mapa salvo do Cenario1 + modo *localization* no lugar de SLAM *mapping* | mapa ao vivo cobria só 15,3 × 13,9 m; 3 de 5 destinos ficavam fora e o Nav2 abortava em < 1 s | casa inteira (29,1 × 26,1 m) navegável |
| 2 | Troca do localizador: `slam_toolbox` → **AMCL** com mapa estático | scan matching puro divergia em travessias longas: erro cresceu de 0,25 m para 18,46 m numa sessão | erro médio caiu para **1,26 m** nas missões bem-sucedidas |
| 3 | Velocidade reduzida: `max_vel_x` 0,5 → **0,26 m/s**, `max_vel_theta` 2,5 → 1,0 | patinação em alta velocidade corrompia o modelo de movimento do AMCL | a rota até a cozinha, que falhava em **todas** as tentativas, passou a chegar a **0,19 m** do alvo |
| 4 | `/initialpose` publicado de forma repetida (`-t 6 -r 1`) | `--once` encerra o publicador antes do discovery do DDS e o AMCL nunca recebia a pose | relocalização confiável no setup de cada execução |
| 5 | Verificação da pós-condição pela **pose verdadeira do Gazebo** | o TF chegou a reportar (-0,65, 0,61) com o robô em (-8,08, -7,12) | **0 discordâncias em 50 execuções** |
| 6 | Tolerância de meta: 0,25 m / 0,25 rad → **0,50 m / 3,14 rad** | o robô parava a 2,03 m da sala oscilando sem fechar a meta | metas fechando normalmente |
| 7 | Cancelamento da meta no timeout via `/nav_cancel` + casamento do resultado com a meta pedida | resultado atrasado de uma navegação era lido como resposta da seguinte; 4 destinos "falharam" em 0,0 s | eliminado |
| 8 | Despausa automática do Gazebo + espera do `/clock` antes do Nav2 | Gazebo abre pausado, Nav2 ativava pela metade e **rejeitava toda meta** em 0,3 s | Nav2 ativo em todas as execuções |

## O que melhorou

**A verificação parou de mentir.** Na Fase D do Teste 1, sem conferência independente,
o sistema teria reportado 3 de 5 destinos alcançados quando apenas 1 foi. No Teste 2,
com verificação pela pose verdadeira, foram **0 discordâncias em 50 execuções**.

**A localização deixou de ser catastrófica.** De 18,46 m de erro acumulado no Teste 1
para 1,26 m médio nas missões bem-sucedidas do Teste 2.

**A navegação ficou viável.** Rotas que falhavam em 100% das tentativas passaram a
concluir.

## O que ainda não está resolvido

A localização continua sendo o fator limitante. Das 15 missões que não cumpriram a
pós-condição no Teste 2, **15 (100%) tinham deriva ≥ 1,5 m** e **nenhuma** falhou com
a pose correta. O erro médio foi de 1,26 m nas bem-sucedidas contra **9,31 m** nas que
falharam.

Em todas as 15 falhas o Planejador gerou planos válidos e o Supervisor esgotou os 6
replanejamentos antes de desistir honestamente. **Nenhuma falha foi de raciocínio.**

## Leitura para o artigo

A separação entre as camadas é o resultado mais forte das duas campanhas: o módulo de
raciocínio multiagente proposto (decomposição, detecção de falha, replanejamento,
relato honesto) funcionou em 100% das execuções; o que limitou o TCR a 70% foi a
localização do robô, que pertence à camada de navegação legada herdada.

Isso delimita com precisão a contribuição do trabalho e aponta o alvo de uma eventual
terceira iteração: melhorar a localização (fusão com odometria visual, tuning do AMCL,
ou landmarks), sem tocar no módulo de raciocínio.
