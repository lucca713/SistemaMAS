#!/bin/bash

# Define o caminho do workspace ajustado para o seu computador
WORKSPACE_DIR=$HOME/ros2_ws

echo "=== Iniciando Sistema do Robô e IA ==="
echo "Workspace: $WORKSPACE_DIR"

# Entrada na pasta do projeto
cd "$WORKSPACE_DIR" || exit 1

# Verifica se o projeto já foi compilado
if [ ! -f "install/setup.bash" ]; then
  echo "ERRO: arquivo install/setup.bash não encontrado! Rode 'colcon build' primeiro."
  exit 1
fi

# Diretório do MAS (Sistema Multi-Agente atualizado)
MAS_DIR="$WORKSPACE_DIR/src/multi-agent/MAS"
# Abre uma única janela do terminal com todas as abas
gnome-terminal --window \
  --tab --title="1-Gazebo" --command="bash -c 'source /opt/ros/humble/setup.bash; source install/setup.bash; ros2 launch robot_bringup gazebo_world.launch.py; exec bash'" \
  --tab --title="2-SLAM/Map" --command="bash -c 'sleep 5; source /opt/ros/humble/setup.bash; source install/setup.bash; ros2 launch robot_bringup mapping.launch.py; exec bash'" \
  --tab --title="3-Nav2" --command="bash -c 'sleep 8; source /opt/ros/humble/setup.bash; source install/setup.bash; ros2 launch robot_bringup navigation_launch.py; exec bash'" \
  --tab --title="4-Teleop" --command="bash -c 'sleep 10; source /opt/ros/humble/setup.bash; source install/setup.bash; ros2 launch robot_bringup teleop_keyboard.launch.py; exec bash'" \
  --tab --title="5-Ollama" --command="bash -c 'sleep 2; ollama serve; exec bash'" \
  --tab --title="6-IA MAS" --command="bash -c 'sleep 12; source /opt/ros/humble/setup.bash; source install/setup.bash; cd \"$MAS_DIR\"; python3 main.py; exec bash'"

echo "Sistema Iniciado! Todas as abas abrirão em instantes."