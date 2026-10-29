from setuptools import find_packages, setup

package_name = 'robot_agent'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Victor Fiorio Casarin',
    maintainer_email='victor.casarin@alunos.fho.edu.br',
    description='Robot agent with tools and ROS2 integration',
    license='Apache License 2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'robot_publisher = robot_agent.robot_tools:main',
            'room_subscriber = robot_agent.room_subscriber:main',
            'simple_robot_publisher = robot_agent.simple_robot_publisher:main',
            'test_publisher = robot_agent.test_publisher:main',
        ],
    },
)
