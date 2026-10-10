# ASR ROS 2 USB Link Monitor

`asr_ros2` is a persistent **USB connection and sensor-flow diagnostic** for an ASR Android phone acting as a ROS 2 sensor node. Its report answers a practical question: **can this ROS 2 host see the phone, and are phone sensor messages actually arriving over the USB-tethered network?**

It is a diagnostic tool, not a robot driver or a DDS service. It does not start the phone runtime, make a phone discoverable, or prove that every other ROS 2 computer can reach the phone. The report describes what this host can observe while the helper is running.

This repository contains the ROS 2 host helper only. It does not contain the Android app, implement USB tethering, or replace Cyclone DDS. The phone and host communicate over the IP network created by Android USB tethering.

## Current status

- The helper builds and its six unit tests pass in the existing ROS 2 Lyrical environment.
- A Mac USB-tether test received IMU and compressed-camera messages from the phone; Ubuntu live testing is still pending.
- This is a pre-release repository. The package manifest still has a proprietary license label and placeholder maintainer email. Do not redistribute it until those fields are finalized.

## Requirements

- ROS 2 Lyrical with Python `rclpy`, `launch`, and `launch_ros`.
- Host middleware: `rmw_fastrtps_cpp`.
- Matching `ROS_DOMAIN_ID` on the phone and host (default: `0`).
- An ASR Android app with **Runtime** and **USB DDS** enabled, plus Android USB tethering enabled.

The host can use Fast DDS while the phone uses Cyclone DDS; the two interoperated in the recorded Mac test. The helper is USB-only. Wi-Fi DDS can be checked with an ordinary ROS 2 node or the robot's persistent node.

## Build from source

Clone this repository into a ROS 2 workspace's `src` directory:

```bash
mkdir -p ~/asr_ros2_ws/src
cd ~/asr_ros2_ws/src
git clone https://github.com/ShreyasDamase/asr-ros2-link-monitor.git
cd ..
colcon build --packages-up-to asr_ros2
source install/setup.bash  # use setup.zsh in zsh
```

## Check USB DDS

1. Connect the phone to the host and enable **USB tethering** in Android settings.
2. In **ASR Runtime (Cyclone DDS)**, start the sensor runtime, enable **USB DDS**, and disable **Wi-Fi DDS** for an isolated USB test.
3. In a sourced ROS 2 host environment, make sure the domain and RMW are set:

   ```bash
   export ROS_DOMAIN_ID=0
   export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
   ```

4. Start the persistent monitor:

   ```bash
   ros2 launch asr_ros2 connect.launch.py transport:=usb
   ```

If interface auto-detection does not choose the USB tether, specify it. Examples are `feth0` on some macOS setups or `usb0`/`enx...` on Linux; use the interface name shown by the host OS:

```bash
ros2 launch asr_ros2 connect.launch.py transport:=usb interface:=usb0
```

Stop the monitor with `Ctrl+C`.

## What the report means

Read the report as separate checks, from the host network up through real sensor data:

| Report item | What it tells you | What it does not tell you |
| --- | --- | --- |
| **ASR network link** | The selected host interface exists and has an IPv4 address. | It does not prove that DDS packets reach the phone or that ROS 2 discovery works. |
| **ASR ROS graph** | This host's ROS 2 graph currently includes one or more phone nodes in an `/asr_android_*` namespace. | It does not prove sensor messages are arriving. A visible topic alone is not data flow. |
| **ASR IMU / compressed image** | The expected topic/type is visible and the helper has received recent messages; the report includes count, rate, and message age. | It does not prove that every sensor or every host is working. |
| **ASR battery** | Whether the BatteryState topic is visible and whether any update has arrived. | Battery is event-driven, so a steady rate is not expected. |
| **ASR runtime** | Whether the helper has received a recent status heartbeat from the phone runtime. | It is not a substitute for checking individual sensor message flow. |

The intended successful result is: the USB interface is selected, the phone appears in the ROS graph, and the sensors you need show recent received messages. If the network check passes but the graph check does not, investigate DDS discovery/domain/interface settings. If the graph and topic checks pass but a sensor has no recent messages, investigate the phone runtime, sensor state, and QoS compatibility.

The helper checks the graph and message flow continuously while it runs. Battery updates are event-driven, so a continuous rate is not expected.

The monitor publishes:

- `/asr_ros2/status` — JSON summary of host link, phone nodes, topics, and received messages.
- `/asr_ros2/diagnostics` — ROS 2 `DiagnosticArray` entries for the same health checks.

For example:

```bash
ros2 topic echo /asr_ros2/status
```

Topic visibility alone does not prove message delivery; use the helper's callback counts, rates, and message age to confirm that samples arrive. The helper's own `/asr_ros2/status` and `/asr_ros2/diagnostics` outputs describe this host's observations, not a global ROS 2 network report.

## Important distinction

This helper is a convenient persistent USB test and diagnostics node. It is **not required by DDS** and should not be a required robot dependency. In deployment, any always-running ROS 2 node on the robot can discover and subscribe to the phone. The helper is useful when you specifically want ASR link and sensor-health reporting.

## Troubleshooting

- **No interface selected:** enable USB tethering, inspect the host's IPv4 interfaces, and pass `interface:=<name>`.
- **No ASR node discovered:** confirm USB DDS is enabled, phone tethering is active, and both sides use the same ROS domain.
- **Topics visible but no samples:** confirm the phone runtime and relevant sensors are running; check offered/requested QoS compatibility.
- **Wi-Fi test:** do not launch this USB-only helper. Use a persistent robot node or a ROS 2 subscriber on the Wi-Fi network.

## Release notes

Before public release, select an open-source license, add the corresponding `LICENSE` file, replace the placeholder maintainer contact in `package.xml` and `setup.py`, and complete the Ubuntu live test. Binary ROS distribution through the ROS release process can be considered later; a source release is sufficient to start sharing once the license and metadata are settled.
