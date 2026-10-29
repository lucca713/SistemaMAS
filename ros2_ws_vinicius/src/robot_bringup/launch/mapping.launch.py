from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.substitutions import FindPackageShare
import os

def generate_launch_description():
    # Caminhos de pacotes e arquivos
    pkg_share = FindPackageShare(package='robot_bringup').find('robot_bringup')
    urdf_file = os.path.join(pkg_share, 'worlds', 'robot.urdf')
    # SLAM_MODE=mapping levanta um mapa novo; o padrao 'localization' carrega o
    # mapa ja salvo do Cenario1. Em modo mapping a localizacao derivou ~30 m
    # depois que o robo tombou sobre uma mesa e as rodas patinaram, e o TF
    # passou a reportar posicao falsa -- com mapa pronto isso nao acontece.
    _slam_mode = os.environ.get('SLAM_MODE', 'localization')
    _slam_cfg = ('mapper_params_online_async.yaml' if _slam_mode == 'mapping'
                 else 'mapper_params_localization.yaml')
    slam_params_file = os.path.join(pkg_share, 'config', _slam_cfg)
    print(f'[mapping.launch] SLAM_MODE={_slam_mode} -> {_slam_cfg}')
    rviz_config_file = os.path.join(pkg_share, 'config', 'mapping_config.rviz')
    
    # Lê o URDF do robô
    with open(urdf_file, 'r') as infp:
        robot_desc = infp.read()

    # Argumento de tempo simulado
    use_sim_time = LaunchConfiguration('use_sim_time', default='true')
    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation (Gazebo) clock'
    )

    # Publica a descrição do robô (para TF e visualização no RViz)
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'robot_description': robot_desc,
            'publish_frequency': 30.0,  # Manter sincronizado com odom (30Hz)
        }]
    )

    # Bridge para /joint_states (para o robot_state_publisher)
    joint_state_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='joint_state_bridge',
        arguments=[
            '/joint_states@sensor_msgs/msg/JointState[gz.msgs.Model'
        ],
        output='screen'
    )

    # Bridge ROS <-> Gazebo com QoS otimizado para baixa latência
    cmd_vel_odom_node = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='ros_gz_bridge',
        arguments=[
            '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',
            '/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',  # ROS2 → Gazebo
            '/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',    # Gazebo → ROS2
            '/model/Robot/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V',  # TF do modelo
        ],
        remappings=[
            ('/model/Robot/tf', '/tf'),  # Publica TF do Gazebo
        ],
        parameters=[{
            'use_sim_time': use_sim_time,
            'qos_overrides./tf.publisher.durability': 'volatile',
            'qos_overrides./tf.publisher.reliability': 'reliable',
            'qos_overrides./tf.publisher.history': 'keep_last',
            'qos_overrides./tf.publisher.depth': 1,
        }],
        output='screen'
    )

    # Bridge para o LiDAR
    lidar_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='lidar_bridge',
        arguments=['/lidar@sensor_msgs/msg/LaserScan@gz.msgs.LaserScan'],
        remappings=[('/lidar', '/scan')],
        parameters=[{'use_sim_time': use_sim_time}],
        output='screen'
    )

    # Node de mapeamento (SLAM Toolbox)
    slam_toolbox_node = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[slam_params_file, {'use_sim_time': use_sim_time}]
    )
    
    # Node do RViz (com arquivo de configuração)
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config_file],
        parameters=[{'use_sim_time': use_sim_time}]
    )
    
    # Monitor de odometria (detecta dessincronização)
    odom_monitor_node = Node(
        package='robot_bringup',
        executable='odom_monitor.py',
        name='odom_monitor',
        output='screen',
        parameters=[{'use_sim_time': use_sim_time}]
    )

    return LaunchDescription([
        declare_use_sim_time_cmd,
        robot_state_publisher_node,
        joint_state_bridge,
        cmd_vel_odom_node,
        lidar_bridge,
        slam_toolbox_node,
        rviz_node,
        odom_monitor_node
    ])
