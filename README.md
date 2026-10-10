# ASR ROS 2 host helper

`asr_ros2` is a persistent ROS 2 host node for connecting to the ASR Android Runtime. It discovers the phone's ROS graph, subscribes to available sensor topics, and reports graph visibility separately from actual message delivery. It does not require Foxglove, RQT, or a short-lived ROS 2 CLI command to keep the host participant present.

## Compatibility

- ROS 2 Lyrical, `rclpy`, and `rmw_fastrtps_cpp` on macOS or Linux.
- The phone and host must use the same `ROS_DOMAIN_ID` (the default is `0`).
- The Android app must have the selected DDS path enabled. Sensor publishing also requires the Android sensor runtime and the relevant sensor enabled.
- The live checks recorded below used the existing Pixi ROS 2 Lyrical environment, a Xiaomi Android phone, and macOS. Ubuntu was not live-tested.

The helper checks and reports the selected **host** interface. Supplying `interface:=...` is an interface-check/selection input to the helper; it does not currently install a Fast DDS interface allowlist on the host. Fast DDS uses its default host networking configuration. The Android app separately restricts its DDS participant to the selected phone transport.

## Build in the existing ROS environment

No new library or Pixi package is required. From a shell where the existing Pixi ROS environment is active:

```bash
cd ~/Vanguard/ASR/asrandroid
colcon build --base-paths asr_ros2 --packages-select asr_ros2
source install/setup.zsh  # use setup.bash in bash
```

Check the environment before connecting:

```bash
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<ROS default>}"
```

The selected middleware must resolve to `rmw_fastrtps_cpp`, matching the Android Fast DDS runtime. The helper exits with a clear error if it does not.

## Connect over USB

1. Connect the phone, enable USB tethering, and enable **USB DDS** in the app.
2. Leave **Wi-Fi DDS** off for an isolated USB-path check.
3. Start the persistent host node:

   ```bash
   ros2 launch asr_ros2 connect.launch.py transport:=usb
   ```

If automatic selection reports that the interface is ambiguous or missing, inspect the host addresses (`ifconfig` on macOS or `ip -br -4 addr` on Linux) and specify the tether interface, for example:

```bash
ros2 launch asr_ros2 connect.launch.py transport:=usb interface:=feth0
```

## Connect over Wi-Fi

1. Enable **Wi-Fi DDS** and turn **USB DDS** off in the app.
2. Put the phone and host on a network that allows DDS multicast traffic.
3. Start the host node:

   ```bash
   ros2 launch asr_ros2 connect.launch.py transport:=wifi
   ```

Specify `interface:=en0` on macOS or the wireless interface name on Linux if automatic selection is ambiguous. Keeping both phone paths enabled is supported by the Android app, but test each path independently when diagnosing network issues.

## What it checks

The helper looks for ASR namespaces (`/asr_android_<device-id>`) and subscribes to these topics when their expected types appear:

| Topic suffix | Type | What the helper reports |
|---|---|---|
| `imu` | `sensor_msgs/msg/Imu` | Message count, recent rate, and age; stale after 2 seconds |
| `camera/image/compressed` | `sensor_msgs/msg/CompressedImage` | Message count, recent rate, and age; stale after 5 seconds |
| `battery` | `sensor_msgs/msg/BatteryState` | Event-driven update count, age, and last values; no periodic rate is expected |
| `status` | `std_msgs/msg/String` | Runtime heartbeat; stale after 12 seconds |

It publishes `/asr_ros2/diagnostics` (`diagnostic_msgs/msg/DiagnosticArray`) and `/asr_ros2/status` (`std_msgs/msg/String`, JSON). These reports distinguish:

- A host interface with an IPv4 address.
- An ASR node visible in the ROS graph.
- A topic and message type visible in the graph.
- Actual messages received by the host.

For example, a visible camera topic without callbacks means discovery of the endpoint succeeded, but image delivery has not yet been confirmed.

The Android battery publisher and this helper use transient-local reliable QoS so a late-joining helper can receive the current battery value. The Android service also republishes its cached value when a DDS participant is restarted; the host reports this as an event-driven state update, not a rate.

## Validation

Results from the live Mac/Pixi test session on 2026-10-10:

| Check | Observed result |
|---|---|
| USB-only DDS | Phone discovered on the USB tether path in under 10 seconds; IMU callbacks about 422–423 Hz and compressed images about 30 Hz |
| Wi-Fi-only DDS | Phone discovered on Wi-Fi in under 1 second in the measured run; IMU callbacks about 422 Hz and compressed images about 30 Hz |
| Independence from viewers | Discovery and sensor callbacks worked with the persistent helper; Foxglove and RQT were not needed |
| Link lifecycle | Stopping the helper caused the phone's peer status to return to waiting; restarting the helper restored discovery without restarting the phone app |
| BatteryState | The helper subscribes and reports event-driven samples; check its diagnostic entry on the target device because battery update cadence is platform-dependent |
| Host package build and tests | Passed in the existing Pixi ROS 2 environment; 5 unit tests |
| Android debug build | Passed; the unit-test task reports `NO-SOURCE` |
| Ubuntu live test | Not run |
| Fast DDS Discovery Server mode | Experimental; not part of the validated USB/Wi-Fi path |

The under-10-second target was met in these runs; this is an observed result, not a guarantee for every Wi-Fi network or tethering state. Cold ROS 2 CLI daemon startup/cache behavior can delay `ros2 node list`; it is separate from the persistent helper's live discovery and sensor callbacks.

## Troubleshooting

- **No usable interface:** connect the selected transport and check the host interface name/address. Pass `interface:=...` if auto-selection is ambiguous.
- **No ASR node:** confirm the matching phone DDS toggle, domain ID, middleware, and that the network permits peer discovery.
- **Node/topic visible, but no sensor messages:** confirm the sensor runtime and the particular sensor are enabled; then inspect the relevant diagnostic entry for topic visibility, count, and last-message age.
- **CLI graph differs from helper diagnostics:** the ROS 2 CLI daemon is a separate process and can retain its startup environment/cache. The helper's own graph and callbacks are the primary evidence for this monitor; restart the CLI daemon only if its environment was changed or its view is stale.

Stop the helper with Ctrl+C. It shuts down its ROS node and subscriptions cleanly. The optional Discovery Server launch arguments are experimental and are not needed for ordinary USB or Wi-Fi discovery.

## Public release note

This package is source-buildable but has not been published to the ROS Index or as a binary package. Before an open-source release, replace the current proprietary license metadata and placeholder maintainer contact with the project's chosen license and a real maintainer address.
