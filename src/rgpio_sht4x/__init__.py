from __future__ import annotations

import time
from typing import List, Optional, Tuple

import rgpio


def make_crc_table(poly: int = 0x31) -> List[int]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) & 0xFF) ^ poly
            else:
                crc = (crc << 1) & 0xFF
        table.append(crc)
    return table


CRC_TABLE = make_crc_table()


def crc8_fast(data: bytes, init: int = 0xFF) -> int:
    crc = init
    for byte in data:
        crc = CRC_TABLE[crc ^ byte]
    return crc


class SHT4x:
    SOFT_RESET = 0x94

    # No-heater measurement commands.
    NOHEAT_HIGHPRECISION = 0xFD
    NOHEAT_MEDPRECISION = 0xF6
    NOHEAT_LOWPRECISION = 0xE0

    # Heater-enabled single-shot commands.
    HIGHHEAT_1S = 0x39
    HIGHHEAT_100MS = 0x3A
    MEDHEAT_1S = 0x32
    MEDHEAT_100MS = 0x33
    LOWHEAT_1S = 0x2F
    LOWHEAT_100MS = 0x30

    def __init__(
        self,
        sbc: Optional[rgpio.sbc] = None,
        bus: int = 0,
        address: int = 0x44,
        mode: Optional[int] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        i2c_flags: int = 0,
        show_errors: bool = True,
    ):
        self._owns_sbc = sbc is None
        if sbc is None:
            connect_kwargs = {"show_errors": show_errors}
            if host is not None:
                connect_kwargs["host"] = host
            if port is not None:
                connect_kwargs["port"] = port
            sbc = rgpio.sbc(**connect_kwargs)

        self.sbc = sbc
        if not self.sbc.connected:
            raise RuntimeError("Cannot connect to rgpiod")

        self.mode = mode or self.NOHEAT_HIGHPRECISION
        try:
            self.handle = self.sbc.i2c_open(bus, address, i2c_flags)
        except rgpio.error as exc:
            self._close_owned_connection()
            raise RuntimeError(
                f"Cannot open I2C bus {bus} @ 0x{address:02X}: {exc.value}"
            ) from exc

    def _close_owned_connection(self) -> None:
        if self._owns_sbc and self.sbc is not None and self.sbc.connected:
            self.sbc.stop()

    def _write_byte(self, command: int, action: str) -> None:
        try:
            self.sbc.i2c_write_byte(self.handle, command)
        except rgpio.error as exc:
            raise RuntimeError(f"SHT4x {action} failed: {exc.value}") from exc

    def reset(self) -> None:
        self._write_byte(self.SOFT_RESET, "soft reset")

    def read(self) -> bytes:
        self._write_byte(self.mode, "measure command")

        time.sleep(0.01)
        try:
            count, data = self.sbc.i2c_read_device(self.handle, 6)
        except rgpio.error as exc:
            raise RuntimeError(f"SHT4x read failed: {exc.value}") from exc

        if count != 6:
            raise RuntimeError(f"Expected 6 bytes, got {count}")
        return bytes(data)

    def parse_sht4x(self, buf: bytes) -> Tuple[float, float]:
        if len(buf) != 6:
            raise RuntimeError(f"Expected 6 bytes, got {len(buf)}")

        t_bytes = buf[0:2]
        t_crc = buf[2]
        h_bytes = buf[3:5]
        h_crc = buf[5]

        if crc8_fast(t_bytes) != t_crc:
            raise RuntimeError(
                f"SHT4x temperature CRC fail: {hex(crc8_fast(t_bytes))} != {hex(t_crc)}"
            )
        if crc8_fast(h_bytes) != h_crc:
            raise RuntimeError(
                f"SHT4x humidity CRC fail: {hex(crc8_fast(h_bytes))} != {hex(h_crc)}"
            )

        t_raw = int.from_bytes(t_bytes, "big")
        h_raw = int.from_bytes(h_bytes, "big")

        temperature = -45 + 175 * (t_raw / 65535.0)
        humidity = 100 * (h_raw / 65535.0)
        return temperature, humidity

    @property
    def measurements(self) -> Tuple[float, float]:
        return self.parse_sht4x(self.read())

    def close(self) -> None:
        close_error = None

        if getattr(self, "handle", None) is not None:
            try:
                self.sbc.i2c_close(self.handle)
            except rgpio.error as exc:
                close_error = RuntimeError(f"SHT4x close failed: {exc.value}")
            finally:
                self.handle = None

        self._close_owned_connection()

        if close_error is not None:
            raise close_error

    def __enter__(self) -> "SHT4x":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


__all__ = ["CRC_TABLE", "SHT4x", "crc8_fast", "make_crc_table"]
