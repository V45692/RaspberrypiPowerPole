import struct
import csv
import os

# =====================
# USER SETTINGS
# =====================
INPUT_BIN = "ads1256_data.bin"     # change to your filename
OUTPUT_CSV = "ads1256_data.csv"

VREF = 2.5     # same values used during logging
GAIN = 1

RECORD_SIZE = 16  # bytes (f + i + i + i)

# =====================
# CONVERSION FUNCTION
# =====================
def raw_to_voltage(raw):
    return raw * (VREF / (GAIN * 8388607.0))

# =====================
# MAIN DECODE
# =====================
if not os.path.exists(INPUT_BIN):
    print("Binary file not found.")
    exit()

with open(INPUT_BIN, "rb") as bf, open(OUTPUT_CSV, "w", newline="") as cf:
    writer = csv.writer(cf)

    # CSV header
    writer.writerow([
        "time_s",
        "sensor1_raw", "sensor1_V",
        "sensor2_raw", "sensor2_V",
        "sensor3_raw", "sensor3_V"
    ])

    count = 0

    while True:
        chunk = bf.read(RECORD_SIZE)
        if len(chunk) < RECORD_SIZE:
            break

        t, s1, s2, s3 = struct.unpack("<fiii", chunk)

        v1 = raw_to_voltage(s1)
        v2 = raw_to_voltage(s2)
        v3 = raw_to_voltage(s3)

        writer.writerow([t, s1, v1, s2, v2, s3, v3])
        count += 1

print(f"Decoded {count} samples → {OUTPUT_CSV}")
