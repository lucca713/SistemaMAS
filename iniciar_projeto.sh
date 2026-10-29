#!/bin/bash
# Sobe a pilha inteira do projeto em terminais separados.
#
# Mudancas nesta versao:
#  - passo 5: sobe o navigate_to_goal.py. Ele e o UNICO no que escuta o topico
#    /room; sem ele, a meta publicada pelo agente nao chega no Nav2 e o robo
#    nunca sai do lugar. Antes nao era iniciado por ninguem.
#    Chamado por caminho direto porque o entry point 'ros2 run robot_bringup
#    navigate_to_goal' esta quebrado (scripts/ nao e subpacote de robot_bringup).
#  - passo 6: sobe o Sistema Multi-Agente (MAS/main.py) no lugar do router.py
#    legado, que era o pipeline reativo de passo unico.

WS="$HOME/ros2_ws"
PROJ="$WS/src/multi-agent"
SETUP_ROS="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

NAV_GOAL="$PROJ/ros2_ws_vinicius/src/robot_bringup/scripts/navigate_to_goal.py"
# Waypoints da casa (4 comodos + hall), usados pelo no de navegacao E pelo MAS.
export MAS_GOALS_FILE="${MAS_GOALS_FILE:-$PROJ/ros2_ws_vinicius/src/robot_bringup/config/goals_casa.json}"
MAS_DIR="$PROJ/MAS"

echo "1/7 - Abrindo Gazebo..."
gnome-terminal --title="1-Gazebo" -- bash -c "$SETUP_ROS && ros2 launch robot_bringup gazebo_world.launch.py; exec bash"

echo "Aguardando o Gazebo carregar..."
sleep 12

# Despausa a simulacao por servico. Sem isso o Gazebo abre pausado, o /clock
# nao avanca e o Nav2 (que usa use_sim_time) ativa pela metade: bt_navigator e
# behavior_server ficam 'inactive' e TODA meta e rejeitada.
echo "   despausa automatica do Gazebo..."
for i in 1 2 3 4 5; do
    if ign service -s /world/empty/control --reqtype ignition.msgs.WorldControl \
        --reptype ignition.msgs.Boolean --timeout 3000 --req 'pause: false' >/dev/null 2>&1; then
        echo "   simulacao rodando."
        break
    fi
    sleep 3
done

echo "2/7 - Abrindo SLAM..."
gnome-terminal --title="2-SLAM" -- bash -c "$SETUP_ROS && ros2 launch robot_bringup mapping.launch.py; exec bash"
sleep 3

# Espera o /clock antes de subir o Nav2 (ativacao depende de tempo simulado).
echo "   aguardando o tempo simulado correr..."
sleep 10

echo "3/7 - Abrindo Nav2..."
gnome-terminal --title="3-Nav2" -- bash -c "$SETUP_ROS && ros2 launch robot_bringup navigation_launch.py; exec bash"
sleep 5

echo "4/7 - Abrindo Servidor Ollama..."
if pgrep -x ollama >/dev/null; then
    echo "      (ollama ja esta rodando, pulando)"
else
    gnome-terminal --title="4-Ollama" -- bash -c "ollama serve; exec bash"
    sleep 3
fi

echo "5/7 - Abrindo no de navegacao por objetivos (escuta /room)..."
if [ -f "$NAV_GOAL" ]; then
    gnome-terminal --title="5-NavGoal" -- bash -c "$SETUP_ROS && python3 '$NAV_GOAL'; exec bash"
else
    echo "      AVISO: $NAV_GOAL nao encontrado!"
fi
sleep 3

# MAS_AUTOSTART=0 sobe so a infraestrutura e deixa o agente para ser rodado
# a mao (util para depurar vendo a saida num terminal so).
if [ "${MAS_AUTOSTART:-1}" = "1" ]; then
    echo "6/7 - Abrindo Sistema Multi-Agente (LangGraph + Ollama)..."
    gnome-terminal --title="6-MAS" -- bash -c "$SETUP_ROS && cd '$MAS_DIR' && python3 main.py; exec bash"
else
    echo "6/7 - MAS nao iniciado (MAS_AUTOSTART=0). Rode a mao:"
    echo "      cd $MAS_DIR && python3 main.py"
fi

echo "7/7 - Abrindo Controle Manual (Teleop)..."
gnome-terminal --title="7-Teleop" -- bash -c "$SETUP_ROS && ros2 launch robot_bringup teleop_keyboard.launch.py; exec bash"

echo
echo "Todos os servicos foram acionados!"
echo "Lembre de dar PLAY no Gazebo para o tempo simulado comecar a correr."
