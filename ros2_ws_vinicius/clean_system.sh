#!/bin/bash

echo "============================================"
echo "🧹 LIMPANDO PROCESSOS E REINICIANDO SISTEMA"
echo "============================================"
echo ""

echo "1️⃣ Matando todos os processos ROS2..."
killall -9 rviz2 2>/dev/null
killall -9 gz 2>/dev/null
killall -9 ruby 2>/dev/null
pkill -9 -f "ros2" 2>/dev/null
pkill -9 -f "slam_toolbox" 2>/dev/null
pkill -9 -f "odom_tf_publisher" 2>/dev/null
pkill -9 -f "parameter_bridge" 2>/dev/null
pkill -9 -f "robot_state_publisher" 2>/dev/null

sleep 2

echo "✅ Processos limpos!"
echo ""

echo "2️⃣ Verificando se ainda há nós rodando..."
ros2 node list 2>/dev/null || echo "✅ Nenhum nó ativo"
echo ""

echo "3️⃣ Limpando variáveis de ambiente..."
unset ROS_DOMAIN_ID
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

echo "✅ Ambiente limpo!"
echo ""

echo "============================================"
echo "✅ Sistema limpo! Agora execute:"
echo "   Terminal 1: ros2 launch ros_gz_sim gz_sim.launch.py gz_args:=src/robot_bringup/worlds/main.sdf"
echo "   Terminal 2: ros2 launch robot_bringup mapping.launch.py"
echo "============================================"
