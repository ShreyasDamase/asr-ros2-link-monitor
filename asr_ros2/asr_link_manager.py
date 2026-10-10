"""Persistent ROS graph and ASR sensor health monitor."""

import json
import os
import signal
import sys
import time
from collections import deque

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import BatteryState, CompressedImage, Imu
from std_msgs.msg import String

from asr_ros2.network import resolve_interface, validate_domain_id


ASR_NAMESPACE_PREFIX = "/asr_android_"
SENSOR_TOPICS = {
    "imu": ("imu", Imu, "sensor_msgs/msg/Imu", 2.0),
    "compressed_image": (
        "camera/image/compressed",
        CompressedImage,
        "sensor_msgs/msg/CompressedImage",
        5.0,
    ),
    "battery": ("battery", BatteryState, "sensor_msgs/msg/BatteryState", None),
    "status": ("status", String, "std_msgs/msg/String", 12.0),
}


def is_asr_namespace(namespace, prefix):
    return namespace.rstrip("/").startswith(prefix.rstrip("/"))


class AsrLinkManager(Node):
    def __init__(self):
        super().__init__("asr_link_manager")
        self.declare_parameter("transport", "usb")
        self.declare_parameter("interface", "")
        self.declare_parameter("discovery_server", "")
        self.declare_parameter("asr_namespace_prefix", ASR_NAMESPACE_PREFIX)

        self.transport = self.get_parameter("transport").get_parameter_value().string_value
        if self.transport != "usb":
            raise ValueError("asr_ros2 helper supports USB only; use a regular ROS 2 node to test Wi-Fi DDS")
        self.requested_interface = self.get_parameter("interface").get_parameter_value().string_value
        self.namespace_prefix = (
            self.get_parameter("asr_namespace_prefix").get_parameter_value().string_value.rstrip("/")
            or ASR_NAMESPACE_PREFIX.rstrip("/")
        )
        self.interface, self.addresses, self.interface_details = resolve_interface(
            self.transport, self.requested_interface
        )
        self.discovery_server = self.get_parameter(
            "discovery_server"
        ).get_parameter_value().string_value
        self.domain_id = validate_domain_id(os.environ.get("ROS_DOMAIN_ID", "0"))
        self.rmw_implementation = rclpy.get_rmw_implementation_identifier()

        self._asr_subscriptions = {}
        self._source_metrics = {}
        self._source_status = {}
        self._source_status_received = {}
        self._battery_values = {}
        self._known_namespaces = set()
        self._logged_states = {}
        self._last_graph_refresh = 0.0
        self._last_interface_refresh = time.monotonic()

        self._diagnostics_pub = self.create_publisher(DiagnosticArray, "diagnostics", 10)
        self._status_pub = self.create_publisher(String, "status", 10)
        self._timer = self.create_timer(1.0, self._tick)
        self.get_logger().info(
            f"ASR link monitor started: transport={self.transport}, "
            f"interface={self.interface or 'unavailable'}, addresses={self.addresses}, "
            f"discovery_server={self.discovery_server or 'simple discovery'}, "
            f"domain={self.domain_id}, rmw={self.rmw_implementation}"
        )
        if not self.interface:
            self.get_logger().error(self.interface_details)
        elif len(self.addresses) > 1:
            self.get_logger().warning(
                f"Interface {self.interface} has multiple IPv4 addresses: {self.addresses}"
            )

    def _refresh_graph(self):
        now = time.monotonic()
        if now - self._last_graph_refresh < 1.0:
            return
        self._last_graph_refresh = now

        nodes = self.get_node_names_and_namespaces()
        asr_namespaces = {
            namespace.rstrip("/")
            for _, namespace in nodes
            if is_asr_namespace(namespace, self.namespace_prefix)
        }
        topics = dict(self.get_topic_names_and_types())
        for topic_name in topics:
            for suffix, _, _, _ in SENSOR_TOPICS.values():
                ending = "/" + suffix
                if topic_name.endswith(ending):
                    namespace = topic_name[: -len(ending)]
                    if is_asr_namespace(namespace, self.namespace_prefix):
                        asr_namespaces.add(namespace)
                    break
        self._known_namespaces.update(asr_namespaces)

        for namespace in sorted(self._known_namespaces):
            for key, (suffix, message_type, expected_type, _) in SENSOR_TOPICS.items():
                topic_name = f"{namespace}/{suffix}"
                topic_types = topics.get(topic_name, [])
                if expected_type not in topic_types:
                    continue

                subscription_key = (namespace, key)
                if subscription_key in self._asr_subscriptions:
                    continue

                qos = QoSProfile(
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10,
                    reliability=ReliabilityPolicy.RELIABLE,
                    durability=(
                        DurabilityPolicy.TRANSIENT_LOCAL
                        if key in {"status", "battery"}
                        else DurabilityPolicy.VOLATILE
                    ),
                )
                callback = lambda message, source=namespace, sensor=key: self._on_message(
                    source, sensor, message
                )
                self._asr_subscriptions[subscription_key] = self.create_subscription(
                    message_type, topic_name, callback, qos
                )
                self._source_metrics[(namespace, key)] = {
                    "count": 0,
                    "last_received": None,
                    "recent": deque(),
                }
                self.get_logger().info(
                    f"ASR source discovered: namespace={namespace}, topic={topic_name}, "
                    f"type={expected_type}"
                )

    def _on_message(self, namespace, sensor, message):
        now = time.monotonic()
        metrics = self._source_metrics[(namespace, sensor)]
        metrics["count"] += 1
        metrics["last_received"] = now
        recent = metrics["recent"]
        recent.append(now)
        while recent and now - recent[0] > 10.0:
            recent.popleft()
        if sensor == "status":
            self._source_status[namespace] = message.data
            self._source_status_received[namespace] = now
        elif sensor == "battery":
            self._battery_values[namespace] = {
                "percentage": message.percentage,
                "voltage": message.voltage,
                "temperature": message.temperature,
                "power_supply_status": message.power_supply_status,
            }

    def _sensor_state(self, namespace, sensor, stale_after):
        metrics = self._source_metrics.get((namespace, sensor))
        if metrics is None:
            return {"topic_visible": False, "flowing": False, "count": 0, "age_sec": None, "rate_hz": 0.0}

        last_received = metrics["last_received"]
        age = None if last_received is None else max(0.0, time.monotonic() - last_received)
        recent = metrics["recent"]
        rate = 0.0
        if len(recent) >= 2 and recent[-1] > recent[0]:
            rate = (len(recent) - 1) / (recent[-1] - recent[0])
        return {
            "topic_visible": True,
            "flowing": age is not None and age <= stale_after,
            "count": metrics["count"],
            "age_sec": None if age is None else round(age, 3),
            "rate_hz": round(rate, 2),
        }

    def _status_entry(self, name, level, message, values):
        status = DiagnosticStatus()
        status.name = name
        status.hardware_id = self.interface or "unavailable"
        status.level = level
        status.message = message
        status.values = [KeyValue(key=key, value=str(value)) for key, value in values.items()]
        return status

    def _log_transition(self, key, state, message):
        if self._logged_states.get(key) == state:
            return
        self._logged_states[key] = state
        if state == "OK":
            self._log_info(f"{key}: {message}")
        elif state == "ERROR":
            self._log_error(f"{key}: {message}")
        else:
            self._log_warning(f"{key}: {message}")

    def _log_info(self, message):
        self.get_logger().info(message)

    def _log_warning(self, message):
        self.get_logger().warning(message)

    def _log_error(self, message):
        self.get_logger().error(message)

    def _refresh_interface(self):
        now = time.monotonic()
        if now - self._last_interface_refresh < 3.0:
            return
        self._last_interface_refresh = now

        previous = (self.interface, tuple(self.addresses), self.interface_details)
        self.interface, self.addresses, self.interface_details = resolve_interface(
            self.transport, self.requested_interface
        )
        current = (self.interface, tuple(self.addresses), self.interface_details)
        if current != previous:
            self.get_logger().info(
                f"Host {self.transport} interface changed: "
                f"{previous[0] or 'unavailable'} {list(previous[1])} -> "
                f"{self.interface or 'unavailable'} {self.addresses}: {self.interface_details}"
            )

    def _tick(self):
        self._refresh_interface()
        self._refresh_graph()
        nodes = self.get_node_names_and_namespaces()
        asr_nodes = [
            f"{namespace.rstrip('/')}/{name}"
            for name, namespace in nodes
            if is_asr_namespace(namespace, self.namespace_prefix)
        ]
        self._known_namespaces.update(
            node.rsplit("/", 1)[0] for node in asr_nodes
        )
        namespaces = sorted(self._known_namespaces)
        topics = dict(self.get_topic_names_and_types())
        topic_visibility = {}
        for namespace in namespaces:
            for key, (suffix, _, expected_type, _) in SENSOR_TOPICS.items():
                topic_name = f"{namespace}/{suffix}"
                topic_visibility[f"{namespace}:{key}"] = (
                    expected_type in topics.get(topic_name, [])
                )

        network_ok = self.interface is not None
        network_message = (
            f"{self.interface} has IPv4 {', '.join(self.addresses)}"
            if network_ok
            else self.interface_details
        )
        self._log_transition("network_link", "OK" if network_ok else "ERROR", network_message)

        graph_ok = bool(asr_nodes)
        graph_message = (
            f"{len(asr_nodes)} ASR node(s) visible"
            if graph_ok
            else f"No node found under {self.namespace_prefix}*"
        )
        self._log_transition("asr_graph", "OK" if graph_ok else "WAITING", graph_message)

        sensor_states = {}
        diagnostics = [
            self._status_entry(
                "ASR network link",
                DiagnosticStatus.OK if network_ok else DiagnosticStatus.ERROR,
                network_message,
                {
                    "transport": self.transport,
                    "interface": self.interface or "",
                    "ipv4_addresses": ", ".join(self.addresses),
                    "details": self.interface_details,
                },
            ),
            self._status_entry(
                "ASR ROS graph",
                DiagnosticStatus.OK if graph_ok else DiagnosticStatus.WARN,
                graph_message,
                {
                    "domain_id": self.domain_id,
                    "rmw_implementation": self.rmw_implementation,
                    "nodes": ", ".join(sorted(asr_nodes)),
                    "topics": json.dumps(topic_visibility, sort_keys=True),
                },
            ),
        ]

        for namespace in namespaces:
            for sensor in ("imu", "compressed_image"):
                _, _, expected_type, stale_after = SENSOR_TOPICS[sensor]
                state = self._sensor_state(namespace, sensor, stale_after)
                topic_name = f"{namespace}/{SENSOR_TOPICS[sensor][0]}"
                state["topic_visible"] = (
                    expected_type in topics.get(topic_name, [])
                )
                sensor_states[f"{namespace}:{sensor}"] = state
                flowing = state["flowing"]
                if flowing:
                    message = (
                        f"Receiving {state['rate_hz']} Hz; "
                        f"{state['count']} message(s) total"
                    )
                elif not state["topic_visible"]:
                    message = f"Expected topic/type not visible: {topic_name} [{expected_type}]"
                elif state["age_sec"] is None:
                    message = f"Topic visible but no messages received: {topic_name}"
                else:
                    message = (
                        f"Messages stale ({state['age_sec']}s old; threshold {stale_after}s)"
                    )
                level = DiagnosticStatus.OK if flowing else DiagnosticStatus.WARN
                key = f"{namespace}:{sensor}"
                self._log_transition(key, "OK" if flowing else "WAITING", message)
                diagnostics.append(
                    self._status_entry(
                        f"ASR {sensor} [{namespace}]",
                        level,
                        message,
                        {
                            "topic": topic_name,
                            "message_type": expected_type,
                            "topic_visible": state["topic_visible"],
                            "flowing": flowing,
                            "message_count": state["count"],
                            "age_sec": state["age_sec"],
                            "rate_hz": state["rate_hz"],
                        },
                    )
                )

            battery_metrics = self._source_metrics.get((namespace, "battery"))
            battery_received_at = (
                None if battery_metrics is None else battery_metrics["last_received"]
            )
            battery_age = (
                None
                if battery_received_at is None
                else max(0.0, time.monotonic() - battery_received_at)
            )
            battery_count = 0 if battery_metrics is None else battery_metrics["count"]
            battery_topic = f"{namespace}/battery"
            battery_visible = (
                "sensor_msgs/msg/BatteryState" in topics.get(battery_topic, [])
            )
            battery_message = (
                f"Received {battery_count} event-driven BatteryState update(s); "
                f"last update {battery_age:.1f}s ago"
                if battery_age is not None
                else (
                    "BatteryState topic visible; waiting for its initial sample"
                    if battery_visible
                    else f"BatteryState topic not visible: {battery_topic}"
                )
            )
            sensor_states[f"{namespace}:battery"] = {
                "topic_visible": battery_visible,
                "messages_received": battery_count,
                "last_update_age_sec": (
                    None if battery_age is None else round(battery_age, 3)
                ),
                "values": self._battery_values.get(namespace),
            }
            diagnostics.append(
                self._status_entry(
                    f"ASR battery [{namespace}]",
                    DiagnosticStatus.OK if battery_received_at is not None else DiagnosticStatus.WARN,
                    battery_message,
                    {
                        "topic": battery_topic,
                        "message_type": "sensor_msgs/msg/BatteryState",
                        "topic_visible": battery_visible,
                        "messages_received": battery_count,
                        "last_update_age_sec": battery_age,
                        "values": json.dumps(
                            self._battery_values.get(namespace), sort_keys=True
                        ),
                        "update_semantics": "event-driven; no continuous rate expected",
                    },
                )
            )

        for namespace in namespaces:
            heartbeat = self._source_status.get(namespace)
            received_at = self._source_status_received.get(namespace)
            heartbeat_age = (
                None
                if received_at is None
                else max(0.0, time.monotonic() - received_at)
            )
            heartbeat_fresh = (
                heartbeat_age is not None
                and heartbeat_age <= SENSOR_TOPICS["status"][3]
            )
            heartbeat_message = (
                heartbeat
                if heartbeat_fresh
                else (
                    f"ASR status heartbeat stale ({heartbeat_age:.1f}s old)"
                    if heartbeat_age is not None
                    else "No ASR status heartbeat received"
                )
            )
            diagnostics.append(
                self._status_entry(
                    f"ASR runtime [{namespace}]",
                    DiagnosticStatus.OK if heartbeat_fresh else DiagnosticStatus.WARN,
                    heartbeat_message,
                    {
                        "heartbeat": heartbeat or "",
                        "age_sec": heartbeat_age,
                    },
                )
            )

        array = DiagnosticArray()
        array.header.stamp = self.get_clock().now().to_msg()
        array.status = diagnostics
        self._diagnostics_pub.publish(array)

        status_message = String()
        status_message.data = json.dumps(
            {
                "transport": self.transport,
                "interface": self.interface,
                "ipv4_addresses": self.addresses,
                "domain_id": self.domain_id,
                "rmw_implementation": self.rmw_implementation,
                "network_link_available": network_ok,
                "asr_nodes_visible": sorted(asr_nodes),
                "topics_visible": topic_visibility,
                "sensors": sensor_states,
                "runtime_heartbeats": self._source_status,
            },
            sort_keys=True,
        )
        self._status_pub.publish(status_message)


def main(args=None):
    try:
        domain_id = validate_domain_id(os.environ.get("ROS_DOMAIN_ID", "0"))
    except ValueError as exc:
        print(f"asr_link_manager: {exc}", file=sys.stderr)
        return 2

    if os.environ.get("ROS_LOCALHOST_ONLY", "").strip() == "1":
        print(
            "asr_link_manager: ROS_LOCALHOST_ONLY=1 prevents discovery beyond this host",
            file=sys.stderr,
        )
        return 2

    discovery_range = os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE", "").upper()
    if discovery_range in {"LOCALHOST", "OFFLINE"}:
        print(
            "asr_link_manager: ROS_AUTOMATIC_DISCOVERY_RANGE="
            f"{discovery_range} prevents the required network discovery",
            file=sys.stderr,
        )
        return 2

    try:
        rmw_implementation = rclpy.get_rmw_implementation_identifier()
    except RuntimeError as exc:
        print(f"asr_link_manager: unable to load the selected ROS middleware: {exc}", file=sys.stderr)
        return 2
    if rmw_implementation != "rmw_fastrtps_cpp":
        print(
            "asr_link_manager: Android ASR currently uses Fast DDS; "
            f"host middleware is {rmw_implementation!r}, expected 'rmw_fastrtps_cpp'",
            file=sys.stderr,
        )
        return 2

    rclpy.init(args=args)
    node = None
    try:
        node = AsrLinkManager()
        if node.domain_id != domain_id:
            raise RuntimeError("ROS domain changed while the helper was starting")
        rclpy.spin(node)
    except KeyboardInterrupt:
        # rclpy consumes the first SIGINT as a KeyboardInterrupt. Launch may
        # forward another SIGINT while we destroy subscriptions and the node;
        # ignore follow-up interrupts so cleanup can finish deterministically.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (RuntimeError, ValueError) as exc:
        print(f"asr_link_manager: {exc}", file=sys.stderr)
        return 2
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0
