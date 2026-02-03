import spidev
import RPi.GPIO as GPIO
import time
import os
import shutil
import struct
import subprocess
from datetime import datetime

# =====================
# GPIO PIN DEFINITIONS
# =====================
DRDY_PIN = 17
RST_PIN  = 18
CS_PIN   = 22

# =====================
# ADS1256 COMMANDS
# =====================
CMD_WAKEUP = 0x00
CMD_RDATA  = 0x01
CMD_RESET  = 0xFE
CMD_SYNC   = 0xFC
CMD_WREG   = 0x50

# =====================
# ADS1256 REGISTERS
# =====================
REG_STATUS = 0x00
REG_MUX    = 0x01
REG_ADCON  = 0x02
REG_DRATE  = 0x03

# =====================
# CONFIGURATION
# =====================
VREF = 2.5
GAIN = 1
DRATE_1000SPS = 0xA1
CAPTURE_TIME = 5.0
USB_MOUNT_BASE = "/media/pi"

# =====================
# SPI SETUP
# =====================
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 2000000
spi.mode = 1

GPIO.setmode(GPIO.BCM)
GPIO.setup(DRDY_PIN, GPIO.IN)
GPIO.setup(RST_PIN, GPIO.OUT)
GPIO.setup(CS_PIN, GPIO.OUT)
GPIO.output(CS_PIN, GPIO.HIGH)

# =====================
# LOW-LEVEL FUNCTIONS
# =====================
def wait_drdy():
    while GPIO.input(DRDY_PIN):
        pass

def write_reg(reg, value):
    GPIO.output(CS_PIN, GPIO.LOW)
    spi.xfer2([CMD_WREG | reg, 0x00, value])
    GPIO.output(CS_PIN, GPIO.HIGH)
    time.sleep(0.002)

def send_cmd(cmd):
    GPIO.output(CS_PIN, GPIO.LOW)
    spi.xfer2([cmd])
    GPIO.output(CS_PIN, GPIO.HIGH)
    time.sleep(0.002)

def read_data():
    wait_drdy()
    GPIO.output(CS_PIN, GPIO.LOW)
    spi.xfer2([CMD_RDATA])
    time.sleep(0.00001)
    raw = spi.xfer2([0x00, 0x00, 0x00])
    GPIO.output(CS_PIN, GPIO.HIGH)

    value = (raw[0] << 16) | (raw[1] << 8) | raw[2]
    if value & 0x800000:
        value -= 0x1000000
    return value

# =====================
# ADS1256 FUNCTIONS
# =====================
def ads1256_init():
    GPIO.output(RST_PIN, GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(RST_PIN, GPIO.HIGH)
    time.sleep(0.1)

    send_cmd(CMD_RESET)
    time.sleep(0.1)

    write_reg(REG_STATUS, 0x04)
    write_reg(REG_ADCON, GAIN)
    write_reg(REG_DRATE, DRATE_1000SPS)

def set_diff_channel(pos, neg):
    mux = (pos << 4) | neg
    write_reg(REG_MUX, mux)
    send_cmd(CMD_SYNC)
    send_cmd(CMD_WAKEUP)

def read_all_channels():
    set_diff_channel(0, 1)
    s1 = read_data()
    set_diff_channel(2, 3)
    s2 = read_data()
    set_diff_channel(4, 5)
    s3 = read_data()
    return s1, s2, s3

# =====================
# USB FUNCTIONS
# =====================
def find_usb_mount():
    """
    Returns:
        (device, mountpoint)
        Example: ('/dev/sda1', '/media/hunter/USB')
    """
    try:
        output = subprocess.check_output(
            ["lsblk", "-o", "NAME,RM,MOUNTPOINT", "-nr"],
            text=True
        )

        for line in output.splitlines():
            parts = line.split(None, 2)

            if len(parts) < 3:
                continue

            name, rm, mount = parts

            # RM=1 means removable (USB flash drive)
            if rm == "1" and mount.startswith("/"):
                device = "/dev/" + name
                return device, mount

    except Exception as e:
        print("USB detection error:", e)

    return None, None

def eject_usb(device, mount_path):
    try:
        print("Syncing filesystem...")
        subprocess.run(["sync"])

        print("Unmounting:", mount_path)
        subprocess.run(["umount", mount_path], check=True)

        print("Powering off USB device:", device)
        subprocess.run(["udisksctl", "power-off", "-b", device])

        print("USB safely ejected.")

    except Exception as e:
        print("USB eject failed:", e)


# =====================
# MAIN
# =====================
try:
    ads1256_init()
    print("ADS1256 initialized")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bin_file = f"ads1256_{timestamp}.bin"
    meta_file = f"ads1256_{timestamp}_meta.csv"

    start_time = time.time()

    with open(bin_file, "wb") as bf:
        while (time.time() - start_time) < CAPTURE_TIME:
            t = time.time() - start_time
            s1, s2, s3 = read_all_channels()
            bf.write(struct.pack("<fiii", t, s1, s2, s3))

    with open(meta_file, "w") as mf:
        mf.write("field,description\n")
        mf.write("timestamp_s,float32 seconds since start\n")
        mf.write("sensor1,int32 raw ADC\n")
        mf.write("sensor2,int32 raw ADC\n")
        mf.write("sensor3,int32 raw ADC\n")
        mf.write(f"Vref,{VREF}\n")
        mf.write(f"Gain,{GAIN}\n")

    print("Binary capture complete")

    print("Searching for removable USB drives...")
    device, usb_path = find_usb_mount()
    print("Detected device:", device)
    print("Detected mount :", usb_path)

    if usb_path:
        shutil.copy(bin_file, usb_path)
        shutil.copy(meta_file, usb_path)
        eject_usb(device, usb_path)
    else:
        print("No removable USB drive detected.")


except KeyboardInterrupt:
    print("Interrupted")

finally:
    spi.close()

    GPIO.cleanup()


