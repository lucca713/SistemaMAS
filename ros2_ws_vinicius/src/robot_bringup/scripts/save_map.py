#!/usr/bin/env python3
"""
Salvar o mapa gerado pelo SLAM Toolbox:
    ros2 run robot_bringup save_map.py [nome_do_mapa]
    
Exemplo:
    ros2 run robot_bringup save_map.py meu_ambiente
"""

import rclpy
from rclpy.node import Node
from slam_toolbox.srv import SaveMap, SerializePoseGraph
import sys
import os


class MapSaver(Node):
    def __init__(self, map_name):
        super().__init__('map_saver')
        self.map_name = map_name
        
        # Clientes de serviço
        self.save_map_client = self.create_client(
            SaveMap, 
            '/slam_toolbox/save_map'
        )
        self.serialize_client = self.create_client(
            SerializePoseGraph,
            '/slam_toolbox/serialize_map'
        )
        
        self.get_logger().info(f'Salvando mapa como: {map_name}')
        
    def save_map(self):
        """Salva o mapa usando o serviço save_map"""
        
        # Aguardar serviço estar disponível
        self.get_logger().info('Aguardando serviço /slam_toolbox/save_map...')
        if not self.save_map_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('Serviço save_map não disponível!')
            return False
        
        # Criar requisição
        request = SaveMap.Request()
        request.name.data = self.map_name
        
        # Chamar serviço
        self.get_logger().info('Salvando mapa...')
        future = self.save_map_client.call_async(request)
        rclpy.spin_until_future_complete(self, future)
        
        if future.result() is not None:
            self.get_logger().info(f'Mapa salvo com sucesso: {self.map_name}.pgm e {self.map_name}.yaml')
            return True
        else:
            self.get_logger().error('Erro ao salvar mapa!')
            return False
    
    def serialize_map(self):
        """Serializa o pose graph usando serialize_map"""
        
        # Aguardar serviço estar disponível
        self.get_logger().info('Aguardando serviço /slam_toolbox/serialize_map...')
        if not self.serialize_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('Serviço serialize_map não disponível!')
            return False
        
        # Criar requisição
        request = SerializePoseGraph.Request()
        request.filename = self.map_name
        
        # Chamar serviço
        self.get_logger().info('Serializando pose graph...')
        future = self.serialize_client.call_async(request)
        rclpy.spin_until_future_complete(self, future)
        
        if future.result() is not None:
            self.get_logger().info(f'Pose graph serializado: {self.map_name}.posegraph')
            return True
        else:
            self.get_logger().error('Erro ao serializar pose graph!')
            return False


def main(args=None):
    rclpy.init(args=args)
    
    # Obter nome do mapa (argumento ou padrão)
    if len(sys.argv) > 1:
        map_name = sys.argv[1]
    else:
        # Nome padrão com timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace = os.path.expanduser('~/ros2_ws')
        map_name = f'{workspace}/maps/map_{timestamp}'
    
    # Se não tem caminho completo, adicionar diretório maps
    if not map_name.startswith('/'):
        workspace = os.path.expanduser('~/ros2_ws')
        map_name = f'{workspace}/maps/{map_name}'
    
    node = MapSaver(map_name)
    
    try:
        # Salvar mapa (gera .pgm e .yaml)
        success_map = node.save_map()
        
        # Serializar pose graph (gera .posegraph)
        success_serialize = node.serialize_map()
        
        if success_map and success_serialize:
            print(f'\n{"="*60}')
            print(f'MAPA SALVO COM SUCESSO!')
            print(f'{"="*60}')
            print(f'Arquivos gerados:')
            print(f'  • {map_name}.yaml       (metadados do mapa)')
            print(f'  • {map_name}.pgm        (imagem do mapa)')
            print(f'  • {map_name}.posegraph  (pose graph serializado)')
            print(f'{"="*60}')
            print(f'\nPara usar este mapa na navegação:')
            print(f'  ros2 launch robot_bringup navigation.launch.py map:={map_name}.yaml')
            print(f'{"="*60}\n')
        else:
            print('\nErro ao salvar mapa!')
            
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
