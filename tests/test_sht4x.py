import importlib
import sys
import types
import unittest
from pathlib import Path


class FakeRgpioError(Exception):
    def __init__(self, value):
        super().__init__(value)
        self.value = value


class FakeSBC:
    def __init__(self, connected=True):
        self.connected = connected
        self.i2c_open_calls = []
        self.i2c_write_calls = []
        self.i2c_close_calls = []
        self.read_responses = []
        self.stop_calls = 0
        self.handle = 12

    def i2c_open(self, bus, address, flags=0):
        self.i2c_open_calls.append((bus, address, flags))
        return self.handle

    def i2c_write_byte(self, handle, value):
        self.i2c_write_calls.append((handle, value))
        return 0

    def i2c_read_device(self, handle, count):
        if not self.read_responses:
            raise AssertionError("No read response queued")
        return self.read_responses.pop(0)

    def i2c_close(self, handle):
        self.i2c_close_calls.append(handle)
        return 0

    def stop(self):
        self.stop_calls += 1
        self.connected = False


class FakeRgpioModule(types.ModuleType):
    def __init__(self):
        super().__init__("rgpio")
        self.error = FakeRgpioError
        self.created_connections = []
        self.next_connection = FakeSBC()

    def sbc(self, **kwargs):
        connection = self.next_connection
        connection.connect_kwargs = kwargs
        self.created_connections.append(connection)
        self.next_connection = FakeSBC()
        return connection


class SHT4xTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

    def setUp(self):
        self.fake_rgpio = FakeRgpioModule()
        sys.modules["rgpio"] = self.fake_rgpio
        for module_name in ("rgpio_sht4x",):
            sys.modules.pop(module_name, None)
        self.module = importlib.import_module("rgpio_sht4x")

    def tearDown(self):
        for module_name in ("rgpio", "rgpio_sht4x"):
            sys.modules.pop(module_name, None)

    def test_measurements_reads_sensor_payload(self):
        sensor_bus = FakeSBC()
        t_bytes = b"\x66\x66"
        h_bytes = b"\x80\x00"
        payload = (
            t_bytes
            + bytes([self.module.crc8_fast(t_bytes)])
            + h_bytes
            + bytes([self.module.crc8_fast(h_bytes)])
        )
        sensor_bus.read_responses.append((6, bytearray(payload)))

        sensor = self.module.SHT4x(sbc=sensor_bus, bus=1)

        temperature, humidity = sensor.measurements

        self.assertAlmostEqual(temperature, 25.0, places=1)
        self.assertAlmostEqual(humidity, 50.0, places=1)
        self.assertEqual(
            sensor_bus.i2c_write_calls,
            [(sensor_bus.handle, self.module.SHT4x.NOHEAT_HIGHPRECISION)],
        )

    def test_close_stops_owned_connection(self):
        sensor = self.module.SHT4x(bus=1, i2c_flags=4, host="pi", port=9999)
        created = self.fake_rgpio.created_connections[0]

        sensor.close()

        self.assertEqual(created.connect_kwargs, {"show_errors": True, "host": "pi", "port": 9999})
        self.assertEqual(created.i2c_open_calls, [(1, 0x44, 4)])
        self.assertEqual(created.i2c_close_calls, [created.handle])
        self.assertEqual(created.stop_calls, 1)

    def test_close_keeps_external_connection_open(self):
        external = FakeSBC()
        sensor = self.module.SHT4x(sbc=external)

        sensor.close()

        self.assertEqual(external.i2c_close_calls, [external.handle])
        self.assertEqual(external.stop_calls, 0)

    def test_init_raises_when_rgpiod_connection_fails(self):
        self.fake_rgpio.next_connection = FakeSBC(connected=False)

        with self.assertRaisesRegex(RuntimeError, "Cannot connect to rgpiod"):
            self.module.SHT4x()

    def test_parse_rejects_short_payload(self):
        sensor = self.module.SHT4x(sbc=FakeSBC())

        with self.assertRaisesRegex(RuntimeError, "Expected 6 bytes, got 5"):
            sensor.parse_sht4x(b"\x00\x01\x02\x03\x04")


if __name__ == "__main__":
    unittest.main()
