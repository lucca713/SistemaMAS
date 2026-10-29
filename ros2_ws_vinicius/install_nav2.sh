#!/bin/bash
# Script para instalar Nav2 e dependências para ROS2 Humble + Gazebo Fortress
# Data: 10/11/2025

echo "=================================================="
echo "  INSTALAÇÃO NAV2 - ROS2 HUMBLE"
echo "=================================================="
echo ""

# Verificar se é ROS2 Humble
if [ -d "/opt/ros/humble" ]; then
    echo "ROS2 Humble detectado"
else
    echo "ROS2 Humble não encontrado!"
    exit 1
fi

echo ""
echo "Instalando pacotes do Nav2 Navigation Stack..."
echo ""

# Atualizar lista de pacotes
sudo apt update

# Instalar Nav2 completo
echo "1. Instalando Navigation2 (nav2-bringup - meta-package)..."
sudo apt install -y ros-humble-navigation2

echo ""
echo "2. Instalando Nav2 Bringup (launch files)..."
sudo apt install -y ros-humble-nav2-bringup

echo ""
echo "3. Instalando AMCL (localização)..."
sudo apt install -y ros-humble-nav2-amcl

echo ""
echo "4. Instalando Map Server..."
sudo apt install -y ros-humble-nav2-map-server

echo ""
echo "5. Instalando Planner Server..."
sudo apt install -y ros-humble-nav2-planner

echo ""
echo "6. Instalando Controller Server..."
sudo apt install -y ros-humble-nav2-controller

echo ""
echo "7. Instalando Behavior Tree Navigator..."
sudo apt install -y ros-humble-nav2-bt-navigator

echo ""
echo "8. Instalando Recoveries Server..."
sudo apt install -y ros-humble-nav2-recoveries

echo ""
echo "9. Instalando Lifecycle Manager..."
sudo apt install -y ros-humble-nav2-lifecycle-manager

echo ""
echo "10. Instalando Costmap 2D..."
sudo apt install -y ros-humble-nav2-costmap-2d

echo ""
echo "11. Instalando Waypoint Follower..."
sudo apt install -y ros-humble-nav2-waypoint-follower

echo ""
echo "12. Instalando Behavior Plugins..."
sudo apt install -y ros-humble-nav2-behaviors

echo ""
echo "13. Instalando SLAM Toolbox (se ainda não instalado)..."
sudo apt install -y ros-humble-slam-toolbox

echo ""
echo "14. Instalando pacotes adicionais úteis..."
sudo apt install -y ros-humble-twist-mux
sudo apt install -y ros-humble-robot-localization

echo ""
echo "=================================================="
echo "  VERIFICANDO INSTALAÇÃO"
echo "=================================================="
echo ""

# Verificar instalação
PACKAGES=(
    "ros-humble-navigation2"
    "ros-humble-nav2-bringup"
    "ros-humble-nav2-amcl"
    "ros-humble-nav2-map-server"
    "ros-humble-nav2-planner"
    "ros-humble-nav2-controller"
    "ros-humble-nav2-bt-navigator"
)

echo "Pacotes instalados:"
for pkg in "${PACKAGES[@]}"; do
    if dpkg -l | grep -q "$pkg"; then
        echo "  $pkg"
    else
        echo "  $pkg (FALHOU)"
    fi
done

echo ""
echo "=================================================="
echo "  INSTALAÇÃO CONCLUÍDA!"
echo "=================================================="
echo ""
echo "Próximos passos:"
echo "  1. Mapear o ambiente:"
echo "     ros2 launch robot_bringup mapping.launch.py"
echo ""
echo "  2. Salvar o mapa:"
echo "     ./quick_save_map.sh meu_ambiente"
echo ""
echo "  3. Visualizar mapa:"
echo "     ros2 launch robot_bringup view_map.launch.py \\"
echo "       map:=/home/vinicius/ros2_ws/maps/meu_ambiente.yaml"
echo ""
echo "  4. Navegação (próximo passo):"
echo "     ros2 launch robot_bringup navigation.launch.py"
echo ""
echo "=================================================="
