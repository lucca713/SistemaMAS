from launch import LaunchDescription
from launch.actions import ExecuteProcess, DeclareLaunchArgument, TimerAction
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    """
    Movimento contínuo do robô usando publicação direta em /cmd_vel.:
    Terminal 1: ros2 launch robot_bringup gazebo_world.launch.py
    Terminal 2: ros2 launch robot_bringup mapping.launch.py
    Terminal 3: ros2 launch robot_bringup cmd_vel.launch.py
    """
    
    # Argumento de tempo simulado
    use_sim_time = LaunchConfiguration('use_sim_time', default='true')
    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation (Gazebo) clock'
    )

    # Bridge ROS <-> Gazebo para /cmd_vel
    # NOTA: Este bridge pode ser omitido se o mapping.launch.py já estiver rodando
    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='cmd_vel_auto_bridge',
        arguments=[
            '/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',  # ROS2 → Gazebo (unidirecional)
        ],
        parameters=[{'use_sim_time': use_sim_time}],
        output='screen'
    )

    # Publicador de comando de velocidade
    publisher = TimerAction(
        period=5.0,  # AGUARDA 5 SEGUNDOS antes de começar a mover (para SLAM estabilizar completamente)
        actions=[
            ExecuteProcess(
                cmd=['ros2', 'topic', 'pub', '/cmd_vel', 'geometry_msgs/msg/Twist',
                     '{linear: {x: 0.18, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.27}}'],
                output='screen'
            )
        ]
    )

    return LaunchDescription([
        declare_use_sim_time_cmd,
        bridge,
        publisher
    ])
