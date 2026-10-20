# Feetech HLS control tables, as read from a hand

Written for whoever needs to work with these servos at register level.

Every value below was read off an assembled ORCA hand, read-only, at 1 Mbaud.
Register names, sizes and units come from Feetech's HLS memory-table manual.
The HLS series shares one memory table, so the layout here is the same for
every HLS motor; only the values differ.

Two motors are shown in full: the wrist (model number 4106, HLS3930M-C001)
and one finger joint (model number 6922, HLS2915M-C001). The other fifteen
finger motors are identical to the one shown except where noted under
"What differs".

## Wrist, model 4106, HLS3930M-C001

### Version (read-only)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 0 | Firmware Major | 1 | R | 3 |  |
| 1 | Firmware Minor | 1 | R | 45 |  |
| 2 | Endianness | 1 | R | 0 |  |
| 3 | Servo Major | 1 | R | 10 |  |
| 4 | Servo Minor | 1 | R | 16 |  |

### EEPROM (configurable, survives power-down)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 5 | Primary ID | 1 | RW | 1 |  |
| 6 | Baud Rate | 1 | RW | 0 | 0=1M 1=500K 2=250K 3=128K 4=115.2K 5=76.8K 6=57.6K 7=38.4K |
| 7 | Secondary ID | 1 | RW | 253 |  |
| 8 | Response Level | 1 | RW | 1 |  |
| 9 | Min Angle Limit | 2 | RW | 0 | 0.087 deg/unit; 0 with addr 11 also 0 selects multi-turn |
| 11 | Max Angle Limit | 2 | RW | 0 | 0.087 deg/unit; 0 with addr 9 also 0 selects multi-turn |
| 13 | Max Temperature | 1 | RW | 80 | deg C |
| 14 | Max Voltage | 1 | RW | 160 | 0.1 V/unit |
| 15 | Min Voltage | 1 | RW | 40 | 0.1 V/unit |
| 16 | Max Torque | 2 | RW | 980 | 0.1 %/unit; loaded into addr 48 at power-up |
| 18 | Phase | 1 | RW | 16 |  |
| 19 | Unload Conditions | 1 | RW | 13 |  |
| 20 | LED Alarm Conditions | 1 | RW | 13 |  |
| 21 | Position P Gain | 1 | RW | 32 |  |
| 22 | Position D Gain | 1 | RW | 32 |  |
| 23 | Position I Gain | 1 | RW | 0 |  |
| 24 | Min Starting Force | 1 | RW | 16 |  |
| 25 | Integral Limit | 1 | RW | 0 | max integral = value x 4; 0 = no limit |
| 26 | CW Dead Zone | 1 | RW | 1 | 0.087 deg/unit |
| 27 | CCW Dead Zone | 1 | RW | 1 | 0.087 deg/unit |
| 28 | Protection Current | 2 | RW | 1000 | 6.5 mA/unit; loaded into addr 44 at power-up |
| 30 | Angle Resolution | 1 | RW | 1 | sensor resolution multiplier |
| 31 | Position Offset | 2 | RW | 280 | 0.087 deg/unit, BIT15 = sign |
| 33 | Operating Mode | 1 | RW | 0 | 0 position, 1 speed, 2 current, 3 PWM |
| 34 | Current P Gain | 1 | RW | 20 |  |
| 35 | Current I Gain | 1 | RW | 10 |  |
| 36 | Reserved | 1 | RW | 255 |  |
| 37 | Speed P Gain | 1 | RW | 20 |  |
| 38 | Overcurrent Time | 1 | RW | 200 | 10 ms/unit |
| 39 | Speed I Gain | 1 | RW | 2 |  |

### SRAM (control)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 40 | Torque Enable | 1 | RW | 0 |  |
| 41 | Acceleration | 1 | RW | 250 | 8.7 deg/s^2 per unit; 0 = max |
| 42 | Goal Position | 2 | RW | 0 | 0.087 deg/unit, BIT15 = sign |
| 44 | Goal Torque | 2 | RW | 1000 | 6.5 mA/unit, -2047..2047 |
| 46 | Goal Speed | 2 | RW | 100 | 0.732 rpm/unit, BIT15 = sign |
| 48 | Torque Limit | 2 | RW | 980 | 0.1 %/unit; from addr 16 |
| 50 | Kp | 1 | RW | 32 |  |
| 51 | Kd | 1 | RW | 32 |  |
| 52 | Ki | 1 | RW | 0 |  |
| 53 | Km | 1 | RW | 0 |  |
| 55 | Lock Flag | 1 | RW | 1 | 0 = EEPROM writes persist, 1 = they do not |

### SRAM (feedback, read-only)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 56 | Present Position | 2 | R | 1889 | 0.087 deg/unit, BIT15 = sign |
| 58 | Present Speed | 2 | R | 0 | 0.732 rpm/unit, BIT15 = sign |
| 60 | Present Load | 2 | R | 0 | 0.1 %/unit, BIT10 = direction |
| 62 | Present Voltage | 1 | R | 121 | 0.1 V/unit |
| 63 | Present Temperature | 1 | R | 30 | deg C |
| 65 | Status | 1 | R | 0 | BIT0 voltage, BIT1 encoder, BIT2 temperature, BIT3 current, BIT5 overload |
| 66 | Moving | 1 | R | 0 | BIT0 moving, BIT1 not yet reached |
| 67 | Target Position | 2 | R | 1889 | 0.087 deg/unit |
| 69 | Present Current | 2 | R | 2 | 6.5 mA/unit, BIT15 = sign |

## Finger joint, model 6922, HLS2915M-C001

### Version (read-only)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 0 | Firmware Major | 1 | R | 3 |  |
| 1 | Firmware Minor | 1 | R | 45 |  |
| 2 | Endianness | 1 | R | 0 |  |
| 3 | Servo Major | 1 | R | 10 |  |
| 4 | Servo Minor | 1 | R | 27 |  |

### EEPROM (configurable, survives power-down)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 5 | Primary ID | 1 | RW | 2 |  |
| 6 | Baud Rate | 1 | RW | 0 | 0=1M 1=500K 2=250K 3=128K 4=115.2K 5=76.8K 6=57.6K 7=38.4K |
| 7 | Secondary ID | 1 | RW | 253 |  |
| 8 | Response Level | 1 | RW | 1 |  |
| 9 | Min Angle Limit | 2 | RW | 0 | 0.087 deg/unit; 0 with addr 11 also 0 selects multi-turn |
| 11 | Max Angle Limit | 2 | RW | 0 | 0.087 deg/unit; 0 with addr 9 also 0 selects multi-turn |
| 13 | Max Temperature | 1 | RW | 80 | deg C |
| 14 | Max Voltage | 1 | RW | 160 | 0.1 V/unit |
| 15 | Min Voltage | 1 | RW | 40 | 0.1 V/unit |
| 16 | Max Torque | 2 | RW | 1000 | 0.1 %/unit; loaded into addr 48 at power-up |
| 18 | Phase | 1 | RW | 52 |  |
| 19 | Unload Conditions | 1 | RW | 13 |  |
| 20 | LED Alarm Conditions | 1 | RW | 0 |  |
| 21 | Position P Gain | 1 | RW | 32 |  |
| 22 | Position D Gain | 1 | RW | 32 |  |
| 23 | Position I Gain | 1 | RW | 0 |  |
| 24 | Min Starting Force | 1 | RW | 8 |  |
| 25 | Integral Limit | 1 | RW | 0 | max integral = value x 4; 0 = no limit |
| 26 | CW Dead Zone | 1 | RW | 0 | 0.087 deg/unit |
| 27 | CCW Dead Zone | 1 | RW | 0 | 0.087 deg/unit |
| 28 | Protection Current | 2 | RW | 450 | 6.5 mA/unit; loaded into addr 44 at power-up |
| 30 | Angle Resolution | 1 | RW | 1 | sensor resolution multiplier |
| 31 | Position Offset | 2 | RW | 35900 | 0.087 deg/unit, BIT15 = sign |
| 33 | Operating Mode | 1 | RW | 0 | 0 position, 1 speed, 2 current, 3 PWM |
| 34 | Current P Gain | 1 | RW | 50 |  |
| 35 | Current I Gain | 1 | RW | 10 |  |
| 36 | Reserved | 1 | RW | 255 |  |
| 37 | Speed P Gain | 1 | RW | 60 |  |
| 38 | Overcurrent Time | 1 | RW | 200 | 10 ms/unit |
| 39 | Speed I Gain | 1 | RW | 20 |  |

### SRAM (control)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 40 | Torque Enable | 1 | RW | 0 |  |
| 41 | Acceleration | 1 | RW | 0 | 8.7 deg/s^2 per unit; 0 = max |
| 42 | Goal Position | 2 | RW | 0 | 0.087 deg/unit, BIT15 = sign |
| 44 | Goal Torque | 2 | RW | 450 | 6.5 mA/unit, -2047..2047 |
| 46 | Goal Speed | 2 | RW | 250 | 0.732 rpm/unit, BIT15 = sign |
| 48 | Torque Limit | 2 | RW | 1000 | 0.1 %/unit; from addr 16 |
| 50 | Kp | 1 | RW | 32 |  |
| 51 | Kd | 1 | RW | 32 |  |
| 52 | Ki | 1 | RW | 0 |  |
| 53 | Km | 1 | RW | 0 |  |
| 55 | Lock Flag | 1 | RW | 1 | 0 = EEPROM writes persist, 1 = they do not |

### SRAM (feedback, read-only)

| Addr | Register | Size | Access | Value | Unit / meaning |
|---:|---|---:|:--:|---:|---|
| 56 | Present Position | 2 | R | 3266 | 0.087 deg/unit, BIT15 = sign |
| 58 | Present Speed | 2 | R | 0 | 0.732 rpm/unit, BIT15 = sign |
| 60 | Present Load | 2 | R | 0 | 0.1 %/unit, BIT10 = direction |
| 62 | Present Voltage | 1 | R | 120 | 0.1 V/unit |
| 63 | Present Temperature | 1 | R | 31 | deg C |
| 65 | Status | 1 | R | 0 | BIT0 voltage, BIT1 encoder, BIT2 temperature, BIT3 current, BIT5 overload |
| 66 | Moving | 1 | R | 0 | BIT0 moving, BIT1 not yet reached |
| 67 | Target Position | 2 | R | 3266 | 0.087 deg/unit |
| 69 | Present Current | 2 | R | 3 | 6.5 mA/unit, BIT15 = sign |

## What differs

### Across the sixteen finger motors

Only two registers vary, and only one of them is interesting.

| Addr | Register | Variation |
|---:|---|---|
| 5 | Primary ID | 2 through 17, one per motor, as expected |
| 31 | Position Offset | different on every motor, see below |

Every other configurable register is byte-identical across all sixteen. So
the finger motors are uniformly configured apart from their identity and
their calibration.

### Between the two models

| Addr | Register | HLS3930M (wrist) | HLS2915M (finger) |
|---:|---|---:|---:|
| 16 | Max Torque | 980 (98.0 %) | 1000 (100.0 %) |
| 18 | Phase | 16 | 52 |
| 20 | LED Alarm Conditions | 13 | 0 |
| 24 | Min Starting Force | 16 | 8 |
| 26 | CW Dead Zone | 1 | 0 |
| 27 | CCW Dead Zone | 1 | 0 |
| 28 | Protection Current | 1000 (6500 mA) | 450 (2925 mA) |
| 34 | Current P Gain | 20 | 50 |
| 37 | Speed P Gain | 20 | 60 |
| 39 | Speed I Gain | 2 | 20 |

These are factory differences between two different motors, not something
the stack sets. Note the dead zones: the finger motors run with none, the
wrist with one unit either side.

## What our stack writes, and what it leaves alone

Searching orca_core's Feetech client for register writes gives a short list.

| Addr | Register | Written by | To what |
|---:|---|---|---|
| 5 | Primary ID | `set_motor_id`, assembly-time chain configuration | the target ID for that position |
| 6 | Baud Rate | `set_baud_rate`, assembly-time | the rate index for 1 Mbaud |
| 31 | Position Offset | `calibrate_offset`, via Feetech's `reOfsCal` | whatever offset makes the current physical position read 3595 or 500 |
| 33 | Operating Mode | `set_control_mode` | 0 for position under current limit |
| 40 | Torque Enable | `set_torque_enabled` | 0 or 1 |
| 41, 42, 44, 46 | Acceleration, Goal Position, Goal Torque, Goal Speed | the motion path, one sync-write block | per command |
| 55 | Lock Flag | around every EEPROM write | 0 to write, 1 to re-lock |

Everything else is left at whatever the motor shipped with. In particular
the stack never writes Protection Current (28), Max Torque (16), the
position PID gains (21 to 23), the current gains (34, 35), the speed gains
(37, 39), or Torque Limit (48).

### Position Offset is the one the stack sets per motor

Calibration calls `calibrate_offset`, which sends Feetech's offset-calibration
instruction asking the servo to make its present physical position read as
3595 (upper) or 500 (lower). The servo computes the offset itself and stores
it in EEPROM, where it survives power cycles. That is why address 31 differs
on every motor while everything else matches: it encodes where each joint's
hardstop happens to sit.

The values on this hand split into two groups, which is worth knowing when
reading them back. Thirteen motors carry a large offset with bit 15 set, the
sign bit, and three carry a small positive one. A raw value above 32768 is
negative: subtract 32768 to get the magnitude in units of 0.087 degrees.

### Protection Current is a trip point, not a rating

Address 28 holds 450 on motors rated 500 mA continuous and stalling at
1.5 A, and 1000 on one rated 800 mA and stalling at 2.8 A. At 6.5 mA per
unit those are 2925 mA and 6500 mA, roughly twice stall in both cases. It is
the overcurrent protection threshold, set high enough that an ordinary stall
does not trip it. It is not a safe continuous ceiling and must not be used
as one.

Because the servo copies address 28 into address 44 at power-up, a motor that
nothing has written to is running with its goal current at that trip point,
which is to say effectively uncapped. orca_core writes a lower value on a
normal connect; a bench that skips that step leaves it wide open.

### Multi-turn is enabled on the hardware

Min Angle Limit and Max Angle Limit both read 0 on every motor, which the
memory table defines as selecting multi-turn. orca_core models this family as
strictly single turn, on the grounds that the turn count is not retained
across a power cycle. Both statements can be true at once, but the servos are
configured for a mode the software does not represent, and anything deriving
a travel range from the software's assumption should be checked against that.
