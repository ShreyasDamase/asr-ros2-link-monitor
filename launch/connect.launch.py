"""Launch the ASR link manager with an explicit host transport."""

import re

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _launch_nodes(context):
    endpoint = LaunchConfiguration("discovery_server").perform(context).strip()
    start_server = LaunchConfiguration("start_server").perform(context).lower() == "true"
    if endpoint and not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}", endpoint):
        raise ValueError("discovery_server must use IPv4:port format")

    actions = []
    if start_server:
        if not endpoint:
            raise ValueError("start_server requires discovery_server:=IPv4:port")
        address, port = endpoint.rsplit(":", 1)
        if any(int(octet) > 255 for octet in address.split(".")) or not 1 <= int(port) <= 65535:
            raise ValueError("discovery_server must use a valid IPv4 address and UDP port")
        actions.append(
            ExecuteProcess(
                cmd=["fastdds", "discovery", "--udp-address", address, "--udp-port", port],
                output="screen",
                sigterm_timeout="5",
            )
        )

    node_kwargs = {}
    if endpoint:
        node_kwargs["additional_env"] = {
            "ROS_DISCOVERY_SERVER": endpoint,
            "ROS_SUPER_CLIENT": "TRUE",
        }
    actions.append(
        Node(
            package="asr_ros2",
            executable="asr_link_manager",
            name="asr_link_manager",
            namespace="asr_ros2",
            output="screen",
            parameters=[
                {
                    "transport": LaunchConfiguration("transport"),
                    "interface": LaunchConfiguration("interface"),
                    "discovery_server": endpoint,
                }
            ],
            **node_kwargs,
        )
    )
    return actions


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "transport",
                default_value="usb",
                description="Selected phone link: usb or wifi",
            ),
            DeclareLaunchArgument(
                "interface",
                default_value="",
                description="Host interface name; auto-detected when unambiguous",
            ),
            DeclareLaunchArgument(
                "discovery_server",
                default_value="",
                description="Fast DDS Discovery Server IPv4 endpoint host:port",
            ),
            DeclareLaunchArgument(
                "start_server",
                default_value="false",
                description="Start a Fast DDS Discovery Server at discovery_server",
            ),
            OpaqueFunction(function=_launch_nodes),
        ]
    )
