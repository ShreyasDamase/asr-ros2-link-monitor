"""Launch the ASR link manager with an explicit host transport."""

import atexit
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from asr_ros2.network import resolve_interface


def _write_fastdds_profile(addresses, discovery_server=""):
    """Create a host Fast DDS profile restricted to the selected network path."""
    interface_rows = "\n".join(
        f'                        <interface name="{escape(address)}" netmask_filter="AUTO"/>'
        for address in addresses
    )
    discovery_server_rows = ""
    if discovery_server:
        address, port = discovery_server.rsplit(":", 1)
        discovery_server_rows = f"""
                        <discoveryProtocol>CLIENT</discoveryProtocol>
                        <discoveryServersList>
                            <locator>
                                <udpv4>
                                    <address>{escape(address)}</address>
                                    <port>{int(port)}</port>
                                </udpv4>
                            </locator>
                        </discoveryServersList>"""
    profile = f"""<?xml version="1.0" encoding="UTF-8" ?>
<dds xmlns="http://www.eprosima.com">
    <profiles>
        <transport_descriptors>
            <transport_descriptor>
                <transport_id>asr_host_udp</transport_id>
                <type>UDPv4</type>
                <interfaces>
                    <allowlist>
{interface_rows}
                    </allowlist>
                </interfaces>
            </transport_descriptor>
        </transport_descriptors>
        <participant profile_name="asr_host_profile" is_default_profile="true">
            <rtps>
                <builtin>
                    <discovery_config>
                        <initialAnnouncements>
                            <count>5</count>
                            <period><sec>0</sec><nanosec>200000000</nanosec></period>
                        </initialAnnouncements>{discovery_server_rows}
                        <leaseDuration><sec>10</sec></leaseDuration>
                        <leaseAnnouncement><sec>2</sec></leaseAnnouncement>
                    </discovery_config>
                </builtin>
                <userTransports>
                    <transport_id>asr_host_udp</transport_id>
                </userTransports>
                <useBuiltinTransports>false</useBuiltinTransports>
            </rtps>
        </participant>
    </profiles>
</dds>
"""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="asr_ros2_fastdds_", suffix=".xml", delete=False
    ) as profile_file:
        profile_file.write(profile)
        path = profile_file.name
    atexit.register(lambda: Path(path).unlink(missing_ok=True))
    return path

def _launch_nodes(context):
    transport = LaunchConfiguration("transport").perform(context).strip()
    interface = LaunchConfiguration("interface").perform(context).strip()
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

    selected_interface, addresses, details = resolve_interface(transport, interface)
    node_env = {}
    if selected_interface and addresses:
        profile_path = _write_fastdds_profile(addresses, endpoint)
        node_env["FASTDDS_DEFAULT_PROFILES_FILE"] = profile_path
        print(
            f"[asr_ros2] Fast DDS host UDPv4 allowlist: "
            f"{selected_interface} -> {', '.join(addresses)}"
        )
    else:
        print(f"[asr_ros2] Fast DDS interface allowlist unavailable: {details}")

    if endpoint:
        node_env.update(
            {
                "ROS_DISCOVERY_SERVER": endpoint,
                "ROS_SUPER_CLIENT": "TRUE",
            }
        )
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
            additional_env=node_env,
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
                description="Host interface name; auto-detected when unambiguous and applied to Fast DDS",
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
