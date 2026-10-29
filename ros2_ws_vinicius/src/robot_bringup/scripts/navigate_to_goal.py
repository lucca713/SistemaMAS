#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String
import json
import sys
import threading
from math import cos, sin
import os

class NavigationGoalClient(Node):
    def __init__(self, goals_file):
        # OBRIGATÓRIO PARA GAZEBO: Passar use_sim_time na inicialização
        super().__init__('navigation_goal_client', parameter_overrides=[rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
        
        # Carregar objetivos do JSON
        with open(goals_file, 'r') as f:
            self.goals = json.load(f)
        
        # Action client para Nav2
        self._action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        
        # Inscrição no tópico /room para integração com o Agente (robot_tools.py)
        self.room_subscriber = self.create_subscription(String, 'room', self.room_callback, 10)
        
        # Publicador de feedback para a IA
        self.result_publisher = self.create_publisher(String, 'nav_result', 10)

        # Cancelamento por topico: o agente pede cancelamento quando estoura o
        # proprio timeout, para nao deixar meta ativa abortando as proximas.
        self.cancel_subscriber = self.create_subscription(
            String, 'nav_cancel', self.cancel_callback, 10)
        
        self.current_goal = None
        self.goal_handle = None
        
        self.get_logger().info('Sistema de Navegação Iniciado!')
        self.get_logger().info(f'[READY] {len(self.goals)} objetivos carregados:')
        for name in self.goals.keys():
            self.get_logger().info(f'   - {name}')
        self.get_logger().info('Digite o nome do objetivo ou "cancel" para cancelar.')
        
    def _publish_result(self, data):
        """Publica em /nav_result. Todo caminho de falha passa por aqui:
        antes, varios deles apenas logavam e o agente ficava esperando no vazio
        ate estourar o timeout."""
        msg = String()
        msg.data = data
        self.result_publisher.publish(msg)
        self.get_logger().info(f'[/nav_result] {data}')

    def room_callback(self, msg):
        goal_name_input = msg.data.strip()
        self.get_logger().info(f'[ROS 2] Recebido comando via tópico /room: "{goal_name_input}"')
        
        # Buscar objetivo case-insensitive
        goal_name = None
        for name in self.goals.keys():
            if name.lower() == goal_name_input.lower():
                goal_name = name
                break
        
        if goal_name:
            self.send_goal(goal_name)
        else:
            self.get_logger().error(f'[ERROR] Objetivo "{goal_name_input}" recebido pelo /room não encontrado no JSON!')
            self._publish_result(f'error:{goal_name_input}:unknown_goal')

    def cancel_callback(self, msg):
        self.get_logger().warn(f'[ROS 2] Cancelamento pedido via /nav_cancel: "{msg.data}"')
        self.cancel_goal()

    def send_goal(self, goal_name):
        if goal_name not in self.goals:
            self.get_logger().error(f'[ERROR] Objetivo "{goal_name}" não encontrado!')
            self.get_logger().info(f'Objetivos disponíveis: {list(self.goals.keys())}')
            self._publish_result(f'error:{goal_name}:unknown_goal')
            return False
        
        # Aguardar servidor Nav2
        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('[ERROR] Nav2 não está rodando!')
            self._publish_result(f'error:{goal_name}:nav2_offline')
            return False
        
        # Criar goal message
        goal_pose = self.goals[goal_name]
        goal_msg = NavigateToPose.Goal()
        
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        
        # OBRIGATÓRIO: Setar o stamp para 0 faz o Nav2 usar a última transformação (TF) disponível, 
        # evitando conflitos entre o relógio do Gazebo e o relógio do sistema (System Time vs Sim Time).
        goal_msg.pose.header.stamp.sec = 0
        goal_msg.pose.header.stamp.nanosec = 0
        
        # Posição
        goal_msg.pose.pose.position.x = goal_pose['x']
        goal_msg.pose.pose.position.y = goal_pose['y']
        goal_msg.pose.pose.position.z = 0.0
        
        # Orientação (conversão de yaw para quaternion)
        yaw = goal_pose['w']
        goal_msg.pose.pose.orientation.x = 0.0
        goal_msg.pose.pose.orientation.y = 0.0
        goal_msg.pose.pose.orientation.z = sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = cos(yaw / 2.0)
        
        self.get_logger().info(f'Navegando para: {goal_name}')
        self.get_logger().info(f'     X={goal_pose["x"]:.2f}, Y={goal_pose["y"]:.2f}, Yaw={goal_pose["w"]:.2f} rad')
        
        # Enviar goal
        self.current_goal = goal_name
        send_goal_future = self._action_client.send_goal_async(
            goal_msg,
            feedback_callback=self.feedback_callback
        )
        send_goal_future.add_done_callback(self.goal_response_callback)
        
        return True
    
    def goal_response_callback(self, future):
        self.goal_handle = future.result()
        if not self.goal_handle.accepted:
            self.get_logger().error('[ERROR] Objetivo rejeitado pelo Nav2!')
            self._publish_result(f'error:{self.current_goal}:rejected')
            self.current_goal = None
            return
        
        self.get_logger().info('Objetivo aceito! Navegando...')
        
        # Aguardar resultado
        result_future = self.goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)
    
    def feedback_callback(self, feedback_msg):
        # Feedback do Nav2 (distância restante, tempo estimado, etc)
        pass
    
    def result_callback(self, future):
        result = future.result().result
        status = future.result().status
        
        msg = String()
        if status == 4:  # SUCCEEDED
            self.get_logger().info(f'OBJETIVO ALCANÇADO: {self.current_goal}')
            msg.data = f'success:{self.current_goal}'
        elif status == 5:  # CANCELED
            self.get_logger().warn(f'[WARNING] Objetivo cancelado: {self.current_goal}')
            msg.data = f'canceled:{self.current_goal}'
        else:
            self.get_logger().error(f'[ERROR] Falha ao alcançar: {self.current_goal} (status: {status})')
            msg.data = f'error:{self.current_goal}:{status}'
            
        self.result_publisher.publish(msg)
        
        self.current_goal = None
        self.goal_handle = None
    
    def cancel_goal(self):
        if self.goal_handle is None:
            self.get_logger().warn('[WARNING] Nenhum objetivo ativo para cancelar.')
            return False
        
        self.get_logger().info(f'Cancelando objetivo: {self.current_goal}')
        cancel_future = self.goal_handle.cancel_goal_async()
        cancel_future.add_done_callback(self.cancel_done_callback)
        return True
    
    def cancel_done_callback(self, future):
        cancel_response = future.result()
        if len(cancel_response.goals_canceling) > 0:
            self.get_logger().info('[READY] Objetivo cancelado com sucesso!')
        else:
            self.get_logger().warn('[ERROR] Falha ao cancelar objetivo.')


def main():
    rclpy.init()
    
    # Caminho do arquivo JSON
    # Caminho derivado da localizacao deste arquivo (antes era absoluto e
    # so funcionava na maquina do autor). MAS_GOALS_FILE sobrescreve.
    _here = os.path.dirname(os.path.abspath(__file__))
    goals_file = os.environ.get(
        'MAS_GOALS_FILE',
        os.path.join(_here, '..', 'config', 'goalsTest.json'))
    goals_file = os.path.abspath(goals_file)
    print(f'[INFO] Metas: {goals_file}')
    
    try:
        node = NavigationGoalClient(goals_file)
    except FileNotFoundError:
        print(f'[ERROR] Arquivo não encontrado: {goals_file}')
        return
    except json.JSONDecodeError:
        print(f'[ERROR] Erro ao ler JSON: {goals_file}')
        return
    
    # Thread para ROS2 spin
    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()
    
    print('\n' + '='*50)
    print('SISTEMA DE NAVEGAÇÃO POR OBJETIVOS')
    print('='*50)
    
    # Loop de input do usuário
    try:
        while rclpy.ok():
            try:
                user_input = input('\n Digite o objetivo (ou "cancel"): ').strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'cancel':
                    node.cancel_goal()
                elif user_input.lower() in ['exit', 'quit']:
                    print('Encerrando...')
                    break
                else:
                    # Buscar objetivo case-insensitive
                    goal_name = None
                    for name in node.goals.keys():
                        if name.lower() == user_input.lower():
                            goal_name = name
                            break
                    
                    if goal_name:
                        node.send_goal(goal_name)
                    else:
                        print(f'[ERROR] Objetivo "{user_input}" não encontrado!')
                        print(f'Disponíveis: {list(node.goals.keys())}')
                        
            except EOFError:
                break
                
    except KeyboardInterrupt:
        print('\nInterrompido pelo usuário')
    
    finally:
        if node.current_goal:
            node.cancel_goal()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
