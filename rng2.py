#!/usr/bin/env python3
import subprocess
import secrets
import sys
import multiprocessing
import random

# ====== Ayarlar ======
FOUND_FILE   = "ALL.txt"
RANGE_SIZE   = 39  # tarama bloğu büyüklüğü (bit)
SKIP_MIN     = 51
SKIP_MAX     = 64

LOWER_BOUND  = 0x400000000000000000
UPPER_BOUND  = 0x7fffffffffffffffff
BLOCK_SIZE   = 1 << RANGE_SIZE
KEYSPACE_LEN = UPPER_BOUND - LOWER_BOUND + 1
MAX_OFFSET   = KEYSPACE_LEN - BLOCK_SIZE

# ====== Fonksiyonlar ======
def random_start():
    low_blk  = LOWER_BOUND >> RANGE_SIZE
    high_blk = UPPER_BOUND >> RANGE_SIZE
    count    = high_blk - low_blk + 1
    blk_idx  = secrets.randbelow(count) + low_blk
    return blk_idx << RANGE_SIZE

def wrap_inc(start_int: int, inc: int) -> int:
    off = (start_int - LOWER_BOUND + inc) % (MAX_OFFSET + 1)
    return LOWER_BOUND + off

def run_gpu(gpu_id):
    print(f"🎯 GPU {gpu_id} başlatılıyor (range: {hex(LOWER_BOUND)} – {hex(UPPER_BOUND)})")
    start_int = random_start()

    scan_ct = 0
    while True:
        hex_start = format(start_int, 'X')
        print(f"🚀 GPU {gpu_id} – scanning: {hex_start} (2^{RANGE_SIZE} keys)")

        try:
            subprocess.run([
                "./vanitysearch",
                "-gpuId", str(gpu_id),
                "-o", FOUND_FILE,
                "-start", hex_start,
                "-range", str(RANGE_SIZE)
            ], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ GPU {gpu_id} – vanitysearch hatası: {e}")
            break

        # Skip mantığı: her taramadan sonra 51–64 bit arası kaydır
        bit_skip = random.randint(SKIP_MIN, SKIP_MAX)
        skip_amt = 1 << bit_skip
        start_int = wrap_inc(start_int, skip_amt)

        scan_ct += 1
        if scan_ct % 10 == 0:
            print(f"[GPU {gpu_id}] [STATUS] scans={scan_ct}, next=0x{start_int:x}")

# ====== Main ======
if __name__ == "__main__":
    try:
        processes = []
        for gpu_id in [0, 1]:  # istediğin GPU id listesi
            p = multiprocessing.Process(target=run_gpu, args=(gpu_id,))
            p.start()
            processes.append(p)

        for p in processes:
            p.join()

    except KeyboardInterrupt:
        print("\n🛑 Kullanıcı tarafından durduruldu.")
        sys.exit(0)
