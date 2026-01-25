import struct

with open("ads1256_XXXX.bin", "rb") as f:
    while chunk := f.read(16):
        t, s1, s2, s3 = struct.unpack("<fiii", chunk)
        print(t, s1, s2, s3)