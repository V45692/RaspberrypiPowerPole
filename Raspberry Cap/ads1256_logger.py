import spidev
import RPi.GPIO as GPIO
import time
import struct
import threading
import subprocess
import json
import os
import shutil
from datetime import datetime

# =====================================================
# GPIO PINS
# =====================================================
DRDY_PIN = 17
RST_PIN  = 18
CS_PIN   = 22

# =====================================================
# ADS1256 CONSTANTS
# =====================================================
CMD_WREG   = 0x50
CMD_RESET  = 0xFE
CMD_RDATAC = 0x03

REG_STATUS = 0x00
REG_MUX    = 0x01
REG_ADCON  = 0x02
REG_DRATE  = 0x03

GAIN = 1
DRATE_3750SPS = 0xC0      # ~1kSPS per channel for 3 channels

CHANNELS = [(0,1),(2,3),(4,5)]
CAPTURE_TIME = 5.0

# =====================================================
# SPI INIT
# =====================================================
spi = spidev.SpiDev()
spi.open(0,0)
spi.max_speed_hz = 3000000
spi.mode = 1

GPIO.setmode(GPIO.BCM)
GPIO.setup(DRDY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(RST_PIN, GPIO.OUT)
GPIO.setup(CS_PIN, GPIO.OUT)
GPIO.output(CS_PIN, GPIO.HIGH)

# =====================================================
# LOW LEVEL ADS1256
# =====================================================
def write_reg(reg, val):
    GPIO.output(CS_PIN, GPIO.LOW)
    spi.xfer2([CMD_WREG | reg, 0x00, val])
    GPIO.output(CS_PIN, GPIO.HIGH)
    time.sleep(0.001)

def send_cmd(cmd):
    GPIO.output(CS_PIN, GPIO.LOW)
    spi.xfer2([cmd])
    GPIO.output(CS_PIN, GPIO.HIGH)
    time.sleep(0.001)

def set_mux_fast(pos, neg):
    mux = (pos<<4)|neg
    GPIO.output(CS_PIN, GPIO.LOW)
    spi.xfer2([CMD_WREG | REG_MUX, 0x00, mux])
    GPIO.output(CS_PIN, GPIO.HIGH)

def read_continuous_raw():
    GPIO.output(CS_PIN, GPIO.LOW)
    raw = spi.xfer2([0x00,0x00,0x00])
    GPIO.output(CS_PIN, GPIO.HIGH)

    value = (raw[0]<<16)|(raw[1]<<8)|raw[2]
    if value & 0x800000:
        value -= 0x1000000
    return value

# =====================================================
# ADS1256 INIT
# =====================================================
def ads1256_init():
    GPIO.output(RST_PIN, GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(RST_PIN, GPIO.HIGH)
    time.sleep(0.1)

    send_cmd(CMD_RESET)
    time.sleep(0.1)

    write_reg(REG_STATUS, 0x04)
    write_reg(REG_ADCON, GAIN)
    write_reg(REG_DRATE, DRATE_3750SPS)

    send_cmd(CMD_RDATAC)

# =====================================================
# ROBUST USB DETECTION + AUTO MOUNT
# =====================================================
def find_and_mount_usb():
    result = subprocess.run(
        ["lsblk","-J","-o","NAME,RM,TYPE,MOUNTPOINT"],
        capture_output=True,
        text=True
    )
    data = json.loads(result.stdout)

    for block in data["blockdevices"]:
        if block["rm"] and block["type"]=="disk":
            if block.get("children"):
                for part in block["children"]:
                    device="/dev/"+part["name"]
                    mount=part.get("mountpoint")

                    if mount:
                        return mount, block["name"]

                    mount_path="/mnt/usb"
                    os.makedirs(mount_path,exist_ok=True)
                    subprocess.run(["mount",device,mount_path])
                    return mount_path, block["name"]
    return None,None

def eject_usb(device_name):
    subprocess.run(["sync"])
    subprocess.run(["udisksctl","power-off","-b",f"/dev/{device_name}"],
                   stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)

# =====================================================
# INTERRUPT DRIVER
# =====================================================
lock = threading.Lock()
running = True
channel_index = 0
start_time = 0
bf = None

def drdy_callback(channel):
    global channel_index, bf

    if not running:
        return

    with lock:
        raw = read_continuous_raw()
        t = time.time() - start_time

        bf.write(struct.pack("<fii", t, channel_index, raw))

        channel_index = (channel_index + 1) % len(CHANNELS)
        set_mux_fast(*CHANNELS[channel_index])

# =====================================================
# MAIN PROGRAM
# =====================================================
try:
    print("Initializing ADS1256...")
    ads1256_init()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bin_file = f"ads1256_{timestamp}.bin"

    print("Opening binary log:", bin_file)
    bf = open(bin_file,"wb")

    set_mux_fast(*CHANNELS[0])

    start_time = time.time()

    GPIO.add_event_detect(
        DRDY_PIN,
        GPIO.FALLING,
        callback=drdy_callback
    )

    print("Acquiring data (interrupt driven)...")
    time.sleep(CAPTURE_TIME)
    running = False

    GPIO.remove_event_detect(DRDY_PIN)
    bf.close()

    print("Capture finished.")

    # =================================================
    # USB COPY + EJECT
    # =================================================
    print("Searching for USB...")
    usb_mount, usb_dev = find_and_mount_usb()

    if usb_mount:
        print("USB detected at:", usb_mount)
        shutil.copy(bin_file, usb_mount)
        print("File copied to USB.")
        eject_usb(usb_dev)
        print("USB safely ejected.")
    else:
        print("No USB drive found. File kept locally.")

except KeyboardInterrupt:
    running=False
    print("Interrupted")

finally:
    spi.close()
    GPIO.cleanup()
