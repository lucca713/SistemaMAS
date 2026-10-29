from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.substitutions import FindPackageShare
import os

def generate_launch_description():
    """
    Visualizar mapa salvo no RViz:
    ros2 launch robot_bringup view_map.launch.py map:=/caminho/para/mapa.yaml
    """
    
    # Caminho padrão do mapa
    default_map = os.path.expanduser('~/ros2_ws/maps/mapa.yaml')
    
    # Arquivo de mapa
    declare_map_arg = DeclareLaunchArgument(
        'map',
        default_value=default_map,
        description='Caminho completo para o arquivo .yaml do mapa'
    )
    
    # Argumento de tempo do simulador
    use_sim_time = LaunchConfiguration('use_sim_time', default='true')
    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation (Gazebo) clock'
    )
    
    map_file = LaunchConfiguration('map')
    
    # Map Server - carrega e publica o mapa
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'yaml_filename': map_file,
            'topic_name': 'map',
            'frame_id': 'map'
        }]
    )
    
    # Lifecycle Manager - gerencia o map_server
    lifecycle_manager_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_map',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': True,
            'node_names': ['map_server']
        }]
    )
    
    # RViz para visualização
    pkg_share = FindPackageShare(package='robot_bringup').find('robot_bringup')
    rviz_config_file = os.path.join(pkg_share, 'config', 'view_map.rviz')
    
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config_file],
        parameters=[{'use_sim_time': use_sim_time}]
    )
    
    return LaunchDescription([
        declare_map_arg,
        declare_use_sim_time_cmd,
        map_server_node,
        lifecycle_manager_node,
        rviz_node
    ])
