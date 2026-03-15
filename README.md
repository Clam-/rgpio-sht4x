# rgpio-sht4x
Basic SHT4x implementation using the `rgpio` backend.

`rgpio` talks to an `rgpiod` daemon, so the target SBC must be running
`rgpiod` before you create the sensor object.

```python
from rgpio_sht4x import SHT4x

with SHT4x(bus=1) as sensor:
    temperature_c, humidity_rh = sensor.measurements
    print(temperature_c, humidity_rh)
```

If you already manage the `rgpio` connection yourself, pass an existing
`rgpio.sbc()` instance as `sbc=...`.
