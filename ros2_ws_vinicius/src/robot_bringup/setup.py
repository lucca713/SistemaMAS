from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'robot_bringup'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*')),
        (os.path.join('share', package_name, 'worlds'), glob('worlds/*')),
        (os.path.join('share', package_name, 'scripts'), glob('scripts/*')),
        (os.path.join('share', package_name, 'models', 'Cenarios'), glob('models/Cenarios/*')),
        (os.path.join('share', package_name, 'models', 'Robot'), glob('models/Robot/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='vinicius',
    maintainer_email='vinicius@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'odom_tf_publisher = robot_bringup.scripts.odom_tf_publisher:main',
            'odom_monitor.py = robot_bringup.scripts.odom_monitor:main',
            'save_map.py = robot_bringup.scripts.save_map:main',
            'navigate_to_goal = robot_bringup.scripts.navigate_to_goal:main',
        ],
    },
)
