"""Host interface and ROS environment validation helpers."""

import ipaddress
import platform
import re
import socket
import subprocess


_INTERFACE_NAME = re.compile(r"^[A-Za-z0-9_.:-]+$")
_IPV4 = re.compile(r"\binet(?:\s+addr:)?\s+(\d{1,3}(?:\.\d{1,3}){3})")
_TRANSPORT_PREFIXES = {
    "usb": ("feth", "rndis", "usb", "enx", "enp", "eth"),
    "wifi": ("wlan", "wlp", "wifi"),
}


def validate_domain_id(value):
    try:
        domain_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ROS_DOMAIN_ID must be an integer, got {value!r}") from exc
    if not 0 <= domain_id <= 232:
        raise ValueError(f"ROS_DOMAIN_ID must be between 0 and 232, got {domain_id}")
    return domain_id


def parse_ipv4_addresses(output):
    addresses = []
    for match in _IPV4.finditer(output):
        address = ipaddress.IPv4Address(match.group(1))
        if not (address.is_loopback or address.is_unspecified or address.is_multicast):
            addresses.append(str(address))
    return sorted(set(addresses))


def _interface_is_up(output):
    for flags in re.findall(r"<([^>]+)>", output):
        if "UP" in flags.split(","):
            return True
    return False


def inspect_interface(name):
    if not _INTERFACE_NAME.fullmatch(name):
        return False, [], "interface name contains unsupported characters"

    system = platform.system()
    if system == "Darwin":
        command = ["ifconfig", name]
    elif system == "Linux":
        command = ["ip", "-o", "-4", "addr", "show", "dev", name]
    else:
        return False, [], f"automatic interface inspection is unsupported on {system}"

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=3)
    except FileNotFoundError:
        tool = command[0]
        return False, [], f"required system command {tool!r} is unavailable"
    except subprocess.TimeoutExpired:
        return False, [], f"timed out inspecting interface {name}"

    if result.returncode != 0:
        details = result.stderr.strip() or f"interface {name} was not found"
        return False, [], details

    if system == "Linux":
        try:
            link = subprocess.run(
                ["ip", "-o", "link", "show", "dev", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return False, [], f"unable to inspect interface state: {exc}"
        if link.returncode != 0:
            return False, [], link.stderr.strip() or f"unable to inspect interface {name}"
        is_up = _interface_is_up(link.stdout)
        address_output = result.stdout
    else:
        is_up = _interface_is_up(result.stdout)
        address_output = result.stdout

    addresses = parse_ipv4_addresses(address_output)
    if not is_up:
        return False, addresses, f"interface {name} is down"
    if not addresses:
        return False, [], f"interface {name} has no usable IPv4 address"
    return True, addresses, "interface is up"


def _mac_wifi_interface():
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    blocks = re.split(r"\n\s*\n", result.stdout)
    for block in blocks:
        if re.search(r"Hardware Port:\s*Wi-Fi\b", block, re.IGNORECASE):
            match = re.search(r"Device:\s*(\S+)", block)
            if match:
                return match.group(1)
    return None


def resolve_interface(transport, requested_interface=""):
    if transport not in _TRANSPORT_PREFIXES:
        return None, [], f"transport must be 'usb' or 'wifi', got {transport!r}"

    if requested_interface:
        usable, addresses, details = inspect_interface(requested_interface)
        if usable:
            return requested_interface, addresses, details
        return None, addresses, f"requested interface {requested_interface}: {details}"

    interface_names = [name for _, name in socket.if_nameindex()]
    if transport == "wifi" and platform.system() == "Darwin":
        wifi_name = _mac_wifi_interface()
        candidates = [wifi_name] if wifi_name else []
    else:
        prefixes = _TRANSPORT_PREFIXES[transport]
        candidates = [name for name in interface_names if name.lower().startswith(prefixes)]

    usable_candidates = []
    for candidate in candidates:
        usable, addresses, _ = inspect_interface(candidate)
        if usable:
            usable_candidates.append((candidate, addresses))

    if len(usable_candidates) == 1:
        name, addresses = usable_candidates[0]
        return name, addresses, "selected the only usable interface for this transport"
    if not usable_candidates:
        return None, [], (
            f"no usable {transport} interface found; connect the phone and pass "
            "interface:=<name> if automatic selection does not recognize it"
        )

    names = ", ".join(name for name, _ in usable_candidates)
    return None, [], f"multiple usable {transport} interfaces found ({names}); pass interface:=<name>"
