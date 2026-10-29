#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class RoomSubscriber(Node):

    def __init__(self):
        super().__init__('room_subscriber')
        self.subscription = self.create_subscription(
            String,
            'room',
            self.room_callback,
            10)
        self.subscription  # prevent unused variable warning

    def room_callback(self, msg):
        self.get_logger().info('Room navigation: "%s"' % msg.data)


def main(args=None):
    rclpy.init(args=args)

    room_subscriber = RoomSubscriber()

    rclpy.spin(room_subscriber)

    # Destroy the node explicitly
    # (optional - otherwise it will be done automatically
    # when the garbage collector destroys the node object)
    room_subscriber.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
