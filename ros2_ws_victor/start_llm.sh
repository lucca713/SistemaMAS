#!/bin/bash

# Define o caminho exato onde está o script router.py
# Baseado no seu comando 'ls' anterior: ~/ros2_ws_victor/robot-agent/ros2_ws
ROUTER_DIR=~/ros2_ws_victor/robot-agent/ros2_ws

echo "=== Iniciando IA do Victor (Chatbot + LLM) ==="
echo "Diretório do Router: $ROUTER_DIR"

# Verifica se a pasta existe antes de tentar entrar
if [ ! -d "$ROUTER_DIR" ]; then
    echo "ERRO: A pasta $ROUTER_DIR não foi encontrada."
    exit 1
fi

# Abre o Terminal com 2 Abas
# Aba 1: Roda o servidor do Ollama (Llama/Gemma)
# Aba 2: Carrega o ROS, entra na pasta e roda o router.py
gnome-terminal --window \
  --tab --title="1-Ollama Server" --command="bash -c 'echo \"Iniciando Servidor Ollama...\"; ollama serve; exec bash'" \
  --tab --title="2-Chatbot Router" --command="bash -c 'sleep 5; echo \"Carregando ROS e Router...\"; source /opt/ros/humble/setup.bash; cd $ROUTER_DIR; python3 router.py; exec bash'"

echo "IA Iniciada! Aguarde o Ollama carregar antes de falar com o Chatbot."
