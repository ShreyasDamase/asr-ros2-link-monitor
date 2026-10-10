# ASR ROS 2 USB Link Monitor

`asr_ros2` is a small, persistent ROS 2 host node for checking an ASR Android sensor node over **USB tethering**. It reports graph discovery separately from sensor-message delivery and publishes its own diagnostics.

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

## What success looks like

The console should report the selected host interface and ASR topics as they are discovered. It then reports message counts and rates for flowing sensors. Battery updates are event-driven, so a continuous rate is not expected.

The monitor publishes:

- `/asr_ros2/status` — JSON summary of host link, phone nodes, topics, and received messages.
- `/asr_ros2/diagnostics` — ROS 2 `DiagnosticArray` entries for the same health checks.

For example:

```bash
ros2 topic echo /asr_ros2/status
```

Topic visibility alone does not prove message delivery; use the helper's callback counts and rates to confirm that samples arrive.

## Important distinction

This helper is a convenient persistent USB test and diagnostics node. It is **not required by DDS** and should not be a required robot dependency. In deployment, any always-running ROS 2 node on the robot can discover and subscribe to the phone. The helper is useful when you specifically want ASR link and sensor-health reporting.

## Troubleshooting

- **No interface selected:** enable USB tethering, inspect the host's IPv4 interfaces, and pass `interface:=<name>`.
- **No ASR node discovered:** confirm USB DDS is enabled, phone tethering is active, and both sides use the same ROS domain.
- **Topics visible but no samples:** confirm the phone runtime and relevant sensors are running; check offered/requested QoS compatibility.
- **Wi-Fi test:** do not launch this USB-only helper. Use a persistent robot node or a ROS 2 subscriber on the Wi-Fi network.

## Release notes

Before public release, select an open-source license, add the corresponding `LICENSE` file, replace the placeholder maintainer contact in `package.xml` and `setup.py`, and complete the Ubuntu live test. Binary ROS distribution through the ROS release process can be considered later; a source release is sufficient to start sharing once the license and metadata are settled.
