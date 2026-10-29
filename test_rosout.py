import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import Log

class RosoutListener(Node):
    def __init__(self):
        super().__init__('rosout_listener')
        self.subscription = self.create_subscription(
            Log,
            '/rosout',
            self.listener_callback,
            10)

    def listener_callback(self, msg):
        if 'nav' in msg.name.lower() or 'planner' in msg.name.lower() or 'controller' in msg.name.lower():
            print(f'[{msg.name}] {msg.msg}')

def main():
    rclpy.init()
    node = RosoutListener()
    rclpy.spin(node)

if __name__ == '__main__':
    main()
