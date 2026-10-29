#!/bin/bash
# Script auxiliar para salvar mapa via linha de comando
# Uso: ./quick_save_map.sh [nome_do_mapa]

MAP_NAME=${1:-"ambiente_$(date +%Y%m%d_%H%M%S)"}
MAP_DIR="$(pwd)/maps"
MAP_PATH="${MAP_DIR}/${MAP_NAME}"

echo "=================================================="
echo "  SALVANDO MAPA DO SLAM TOOLBOX"
echo "=================================================="
echo ""
echo "Nome do mapa: ${MAP_NAME}"
echo "Diretório: ${MAP_DIR}"
echo ""

# Verificar se SLAM está rodando
if ! ros2 service list | grep -q "/slam_toolbox/save_map"; then
    echo "  ERRO: SLAM Toolbox não está rodando!"
    echo "  Inicie primeiro: ros2 launch robot_bringup mapping.launch.py"
    exit 1
fi

echo "SLAM Toolbox detectado"
echo ""

# Salvar mapa (gera .yaml e .pgm)
echo "1. Salvando mapa (.yaml e .pgm)..."
ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap "{name: {data: '${MAP_PATH}'}}"

sleep 1

# Serializar pose graph (gera .posegraph)
echo ""
echo "2. Serializando pose graph (.posegraph)..."
ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph "{filename: '${MAP_PATH}'}"

sleep 1

echo ""
echo "=================================================="
echo " MAPA SALVO COM SUCESSO!"
echo "=================================================="
echo ""
echo "Arquivos gerados:"
if [ -f "${MAP_PATH}.yaml" ]; then
    echo " ${MAP_PATH}.yaml"
else
    echo " ${MAP_PATH}.yaml [não encontrado]"
fi

if [ -f "${MAP_PATH}.pgm" ]; then
    echo " ${MAP_PATH}.pgm"
else
    echo " ${MAP_PATH}.pgm [não encontrado]"
fi

if [ -f "${MAP_PATH}.posegraph" ]; then
    echo " ${MAP_PATH}.posegraph"
else
    echo " ${MAP_PATH}.posegraph [opcional]"
fi

echo ""
echo "=================================================="
echo "Próximos passos:"
echo "=================================================="
echo ""
echo "1. Visualizar mapa:"
echo "   eog ${MAP_PATH}.pgm"
echo ""
echo "2. Usar na navegação (futuro):"
echo "   ros2 launch robot_bringup navigation.launch.py \\"
echo "     map:=${MAP_PATH}.yaml"
echo ""
echo "3. Listar mapas salvos:"
echo "   ls -lh ${MAP_DIR}/"
echo ""
echo "=================================================="
