import unittest
from unittest.mock import patch

from asr_ros2.network import (
    parse_ipv4_addresses,
    resolve_interface,
    validate_domain_id,
)
from asr_ros2.asr_link_manager import is_asr_namespace


class NetworkHelpersTest(unittest.TestCase):
    def test_domain_id_bounds(self):
        self.assertEqual(validate_domain_id("0"), 0)
        self.assertEqual(validate_domain_id("232"), 232)
        for value in ("-1", "233", "not-a-domain"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_domain_id(value)

    def test_ipv4_parser_filters_non_usable_addresses(self):
        output = (
            "inet 127.0.0.1/8 scope host lo\n"
            "inet 192.168.1.4/24 brd 192.168.1.255 scope global en0\n"
            "inet 239.1.1.1/24 scope global multicast0\n"
        )
        self.assertEqual(parse_ipv4_addresses(output), ["192.168.1.4"])

    def test_ambiguous_transport_requires_explicit_interface(self):
        with (
            patch("asr_ros2.network.socket.if_nameindex", return_value=[(1, "feth0"), (2, "enx123")]),
            patch(
                "asr_ros2.network.inspect_interface",
                side_effect=[
                    (True, ["10.0.0.1"], "up"),
                    (True, ["10.0.0.2"], "up"),
                ],
            ),
        ):
            interface, addresses, details = resolve_interface("usb")
        self.assertIsNone(interface)
        self.assertEqual(addresses, [])
        self.assertIn("multiple usable usb interfaces", details)

    def test_unknown_transport_is_rejected(self):
        interface, _, details = resolve_interface("bluetooth")
        self.assertIsNone(interface)
        self.assertIn("must be 'usb'", details)

    def test_wifi_transport_is_disabled_for_helper(self):
        interface, _, details = resolve_interface("wifi")
        self.assertIsNone(interface)
        self.assertIn("must be 'usb'", details)

    def test_asr_namespace_prefix_matches_runtime_namespace(self):
        self.assertTrue(is_asr_namespace("/asr_android_168", "/asr_android_"))
        self.assertFalse(is_asr_namespace("/asr_androidish_168", "/asr_android_"))


if __name__ == "__main__":
    unittest.main()
