from launch import LaunchDescription
from launch.actions import ExecuteProcess, SetEnvironmentVariable
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    # Encontra o diretório do pacote
    pkg_share = get_package_share_directory('robot_bringup')
    # Caminho para o mundo SDF
    world_file = os.path.join(pkg_share, 'worlds', 'main.sdf')
    # Caminho para os modelos
    models_path = os.path.join(pkg_share, 'models')
    
    # Encontrar os modelos do Gazebo Fortress 
    set_gz_resource_path = SetEnvironmentVariable(
        name='IGN_GAZEBO_RESOURCE_PATH',
        value=models_path
    )
    
    # Inicia o Gazebo Fortress
    gazebo = ExecuteProcess(
        # NOTA: nao usar '-r' aqui. Com '-r' o processo 'ign' encerrava em ~2s
        # ("finished cleanly") e a simulacao nao subia. Para comecar despausado,
        # chame o servico de controle do mundo depois que o Gazebo abrir:
        #   ign service -s /world/empty/control \
        #     --reqtype ignition.msgs.WorldControl --reptype ignition.msgs.Boolean \
        #     --timeout 3000 --req 'pause: false'
        cmd=['ign', 'gazebo', world_file, '-v', '4'],
        output='screen',
        additional_env={'IGN_GAZEBO_RESOURCE_PATH': models_path}
    )
    
    return LaunchDescription([
        set_gz_resource_path,
        gazebo
    ])
