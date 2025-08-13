#!/usr/bin/env python3
import subprocess
import secrets
import sys
import multiprocessing

# ===== Ayarlar =====
FOUND_FILE   = "ALL.txt"      # istersen "ALL_gpu{gpu_id}.txt" yapıp sonra birleştirebilirsin
PREFIX       = "1PWo3JeB9"    # zorunlu prefix
RANGE_SIZE   = 42             # tarama bloğu büyüklüğü (bit)
SKIP_MIN     = 51
SKIP_MAX     = 64
NUM_GPUS     = 2

LOWER_BOUND  = 0x400000000000000000
UPPER_BOUND  = 0x7fffffffffffffffff
BLOCK_SIZE   = 1 << RANGE_SIZE
KEYSPACE_LEN = UPPER_BOUND - LOWER_BOUND + 1
MAX_OFFSET   = KEYSPACE_LEN - BLOCK_SIZE

# ===== Yardımcılar =====
def random_block_start() -> int:
    # Rastgele blok seçer (blok = 2^RANGE_SIZE hizalı)
    low_blk  = LOWER_BOUND >> RANGE_SIZE
    high_blk = UPPER_BOUND >> RANGE_SIZE
    count    = high_blk - low_blk + 1
    blk_idx  = secrets.randbelow(count) + low_blk
    return blk_idx << RANGE_SIZE

def block_index(start_int: int) -> int:
    return (start_int - LOWER_BOUND) >> RANGE_SIZE

def wrap_inc(start_int: int, inc: int) -> int:
    # inc mutlaka BLOCK_SIZE'ın katı olmalı (bizde 2^51..2^64 olduğu için zaten katı)
    off = (start_int - LOWER_BOUND + inc) % (MAX_OFFSET + 1)
    return LOWER_BOUND + off

def rand_bit_skip() -> int:
    return secrets.randbelow(SKIP_MAX - SKIP_MIN + 1) + SKIP_MIN  # [51,64]

def aligned_random_start_for_gpu(gpu_id: int) -> int:
    # Her GPU'ya farklı "blok sınıfı" (mod NUM_GPUS) veriyoruz.
    # Skip adımları 2^k olduğu için blok sınıfı sabit kalır; bu sayede çakışma olmaz.
    while True:
        s = random_block_start()
        if block_index(s) % NUM_GPUS == gpu_id:
            return s

# ===== Çalıştırıcı =====
def run_gpu(gpu_id: int):
    print(f"🎯 GPU {gpu_id} başlatılıyor (range: {hex(LOWER_BOUND)} – {hex(UPPER_BOUND)})")

    start_int = aligned_random_start_for_gpu(gpu_id)
    scans = 0

    while True:
        hex_start = format(start_int, 'X')
        print(f"🚀 GPU {gpu_id} – scanning: {hex_start} (2^{RANGE_SIZE} keys, prefix: {PREFIX})")

        try:
            subprocess.run([
                "./vanitysearch",
                "-gpuId", str(gpu_id),
                "-o", FOUND_FILE,
                "-start", hex_start,
                "-range", str(RANGE_SIZE),
                PREFIX
            ], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ GPU {gpu_id} – vanitysearch hatası: {e}")
            break

        # 51–64 bit arası rastgele skip
        bit_skip = rand_bit_skip()
        skip_amt = 1 << bit_skip
        start_int = wrap_inc(start_int, skip_amt)

        scans += 1
        if scans % 10 == 0:
            cls = block_index(start_int) % NUM_GPUS
            print(f"[GPU {gpu_id}] scans={scans}, next=0x{start_int:x}, class={cls}")

# ===== Main =====
if __name__ == "__main__":
    try:
        procs = []
        for gpu_id in range(NUM_GPUS):  # [0, 1]
            p = multiprocessing.Process(target=run_gpu, args=(gpu_id,))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

    except KeyboardInterrupt:
        print("\n🛑 Kullanıcı tarafından durduruldu.")
        sys.exit(0)
