# Melhoria no Feedback de Navegação e Física do Nav2

O robô bateu na parede porque a `inflation_radius` (zona de segurança ao redor das paredes) ficou muito pequena (0.3m). Ele tentou "cortar caminho" raspando na parede e a física do simulador o prendeu. Além disso, a IA reportou "sucesso" cegamente porque o `executor.py` estava configurado apenas para dar um `time.sleep(15)` e assumir que deu certo, em vez de esperar a resposta real do ROS 2.

## Proposed Changes

### nav2_params.yaml
Ajustar a `inflation_radius` de `0.3` para `0.6` (tanto no `global_costmap` quanto no `local_costmap`). Isso mantém o robô "magro" (`robot_radius: 0.2`), mas cria um campo de repulsão maior ao redor das paredes, forçando-o a andar pelo meio dos corredores e evitando que ele enrosque nas quinas.

### navigate_to_goal.py
Fazer o nó de navegação publicar o resultado real da missão (Sucesso ou Falha) em um novo tópico chamado `/nav_result` assim que o Nav2 terminar.

### robot_publisher.py e executor.py
Fazer o `robot_publisher` escutar o tópico `/nav_result`. 
Atualizar o `executor.py` para remover o `time.sleep(15)` cego e fazê-lo aguardar ativamente o resultado publicado pelo `navigate_to_goal.py`. Se receber "error", a IA saberá que o robô falhou e poderá tentar um replanejamento real.

## User Review Required
> [!IMPORTANT]
> Aprova a implementação da comunicação bidirecional para que a IA saiba quando o robô realmente falha ou chega ao destino?
