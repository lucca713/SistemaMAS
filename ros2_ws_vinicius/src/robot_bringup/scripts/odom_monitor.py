#!/usr/bin/env python3
"""
Monitor de Odometria - Detecta quando o robô para (colisão) e ajusta publicação.
Ajuda a manter Gazebo e RViz sincronizados.
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
import math

class OdomMonitor(Node):
    def __init__(self):
        super().__init__('odom_monitor')
        
        # Subscreve à odometria do Gazebo
        self.odom_sub = self.create_subscription(
            Odometry,
            '/odom',
            self.odom_callback,
            10
        )
        
        # Subscreve aos comandos de velocidade
        self.cmd_vel_sub = self.create_subscription(
            Twist,
            '/cmd_vel',
            self.cmd_vel_callback,
            10
        )
        
        # Variáveis de estado
        self.last_odom_time = None
        self.last_position = None
        self.cmd_vel_received = None
        self.cmd_vel_time = None
        
        # Timer para verificação periódica
        self.create_timer(1.0, self.check_sync)
        
        self.get_logger().info('Monitor de odometria iniciado')
    
    def odom_callback(self, msg):
        """Callback da odometria"""
        current_time = self.get_clock().now()
        current_pos = msg.pose.pose.position
        
        if self.last_odom_time is not None and self.last_position is not None:
            # Calcular deslocamento
            dt = (current_time - self.last_odom_time).nanoseconds / 1e9
            dx = current_pos.x - self.last_position.x
            dy = current_pos.y - self.last_position.y
            distance = math.sqrt(dx*dx + dy*dy)
            
            # Velocidade atual
            velocity = distance / dt if dt > 0 else 0.0
            
            # Se há comando de velocidade mas robô parado = colisão
            if self.cmd_vel_received is not None:
                cmd_linear = self.cmd_vel_received.linear.x
                if abs(cmd_linear) > 0.1 and velocity < 0.01:
                    self.get_logger().warn(
                        f'Possível colisão detectada! Cmd: {cmd_linear:.2f} m/s, '
                        f'Vel real: {velocity:.3f} m/s',
                        throttle_duration_sec=2.0
                    )
        
        self.last_odom_time = current_time
        self.last_position = current_pos
    
    def cmd_vel_callback(self, msg):
        """Callback do comando de velocidade"""
        self.cmd_vel_received = msg
        self.cmd_vel_time = self.get_clock().now()
    
    def check_sync(self):
        """Verifica sincronização periodicamente"""
        if self.last_odom_time is None:
            self.get_logger().warn('Nenhuma odometria recebida ainda')
            return
        
        current_time = self.get_clock().now()
        odom_age = (current_time - self.last_odom_time).nanoseconds / 1e9
        
        if odom_age > 1.0:
            self.get_logger().warn(
                f'Odometria desatualizada! Última recebida há {odom_age:.1f}s'
            )

def main(args=None):
    rclpy.init(args=args)
    node = OdomMonitor()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
