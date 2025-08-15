#!/usr/bin/env python3
import secrets
import random
import subprocess
import re
import time
import sys
import errno
import os
import uuid
import hashlib
from multiprocessing import Process, Manager

# ======== GÜVENLİ PRINT WRAPPER ========
original_print = print
def print(*args, **kwargs):
    try:
        original_print(*args, **kwargs)
    except IOError as e:
        if getattr(e, "errno", None) != errno.EAGAIN:
            raise

# ====== KULLANICI AYARLARI ======
KEY_MIN        = int("400000000000000000", 16)
KEY_MAX        = int("7FFFFFFFFFFFFFFFFF", 16)
RANGE_BITS     = 40
BLOCK_SIZE     = 1 << RANGE_BITS
KEYSPACE_LEN   = KEY_MAX - KEY_MIN + 1
MAX_OFFSET     = KEYSPACE_LEN - BLOCK_SIZE

VANITY         = "./vanitysearch"
ALL_FILE       = "ALL1.txt"
PREFIX         = "1PWo3JeB9"  # güncel prefix

CONTINUE_MAP = {
    "1PWo3JeB9jr": 75,
    "1PWo3JeB9j":  10,
    "1PWo3JeB9":   5,
    "1PWo3JeB":    1,
}
DEFAULT_CONTINUE = 1

# ====== SKIP WINDOW PARAMETRELERİ ======
SKIP_CYCLES    = 20
SKIP_BITS_MIN  = 55
SKIP_BITS_MAX  = 64

# ==============================================================================
# ENTROPY/SEED & RANDOM BAŞLANGIÇ
# ==============================================================================
def strong_entropy_seed(gpu_id: int) -> int:
    """
    Her process/GPU için güçlü, benzersiz seed.
    SHA3-512 ile urandom, zaman sayaçları, randbits, token, uuid ve hostname karıştırılır.
    """
    hostname = os.uname().nodename.encode()
    material = b"".join([
        os.urandom(32),
        time.time_ns().to_bytes(8, "big", signed=False),
        time.perf_counter_ns().to_bytes(8, "big", signed=False),
        secrets.token_bytes(16),
        secrets.randbits(256).to_bytes(32, "big"),
        uuid.uuid4().bytes,
        gpu_id.to_bytes(2, "big"),
        os.getpid().to_bytes(4, "big"),
        hostname,
    ])
    digest = hashlib.sha3_512(material).digest()
    return int.from_bytes(digest, "big")

def random_start() -> int:
    """
    KEY_MIN..KEY_MAX aralığında uniform bir nokta seçer ve RANGE_BITS'e hizalar.
    """
    random_offset = secrets.randbelow(KEYSPACE_LEN)
    random_key = KEY_MIN + random_offset
    block_mask = ~((1 << RANGE_BITS) - 1)
    start = random_key & block_mask
    if start < KEY_MIN:
        start = KEY_MIN
    print(f">>> random_start → start=0x{start:x}")
    return start

def random_start_unique(gpu_id: int, used_starts, lock) -> int:
    """
    Tamamen random, GPU-özel entropy ile seed'lenmiş ve diğer GPU'larla çakışmayan başlangıç.
    Manager.Lock ile check+set atomik yapılır.
    """
    while True:
        entropy_val = strong_entropy_seed(gpu_id)
        random.seed(entropy_val)
        candidate = random_start()
        # Atomik check+claim
        with lock:
            if candidate not in used_starts:
                used_starts[candidate] = 1
                print(f"[GPU {gpu_id}] seed_tail={hex(entropy_val)[-16:]}, start=0x{candidate:x}")
                return candidate
        # Çakışma olursa döngü yeni entropy ile devam eder

# ==============================================================================
# YARDIMCI FONKSİYONLAR
# ==============================================================================
def wrap_inc(start: int, inc: int) -> int:
    off = (start - KEY_MIN + inc) % (MAX_OFFSET + 1)
    return KEY_MIN + off

def scan_at(start: int, gpu_id: int):
    sh = f"{start:x}"
    print(f">>> [GPU {gpu_id}] scan start=0x{sh}")
    p = subprocess.Popen(
        [VANITY, "-gpuId", str(gpu_id), "-o", ALL_FILE,
         "-start", sh, "-range", str(RANGE_BITS), PREFIX],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    header_done = False
    hit = False
    addr = priv = None

    for line in p.stdout:
        if not header_done:
            print(line, end="", flush=True)
            if line.startswith("GPU:") or "VanitySearch" in line:
                header_done = True
            continue

        if line.startswith("Public Addr:"):
            hit, addr = True, line.split()[-1].strip()
            print(f"    !! public-hit: {addr}")

        if "Priv (HEX):" in line and hit:
            m = re.search(r"0x\s*([0-9A-Fa-f]+)", line)
            if m:
                priv = m.group(1).zfill(64)
                print(f"    >> privkey: {priv}")

    p.wait()
    return hit, addr, priv

# ==============================================================================
# WORKER
# ==============================================================================
def worker(gpu_id: int, used_starts, lock):
    sorted_pfx      = sorted(CONTINUE_MAP.keys(), key=lambda p: -len(p))
    start           = random_start_unique(gpu_id, used_starts, lock)
    scan_ct         = 0
    initial_window  = 0
    window_rem      = 0
    skip_rem        = 0
    last_main_start = 0

    print(f"\n→ [GPU {gpu_id}] Başlatıldı. CTRL-C ile durdurabilirsiniz\n")

    try:
        while True:
            # ====== MAIN WINDOW ======
            if window_rem > 0:
                last_main_start = start
                hit, addr, priv = scan_at(start, gpu_id)
                scan_ct += 1

                if hit and priv:
                    matched = next((p) for p in sorted_pfx if addr.startswith(p)) if addr else PREFIX
                    new_win = CONTINUE_MAP.get(matched, DEFAULT_CONTINUE)
                    if new_win > initial_window:
                        initial_window = new_win
                        print(f"    >> [GPU {gpu_id}] nadir hit! window={initial_window}")

                window_rem -= 1
                print(f"    >> [GPU {gpu_id}] [MAIN WINDOW] {initial_window-window_rem}/{initial_window}")

                if window_rem > 0:
                    start = wrap_inc(start, BLOCK_SIZE)
                else:
                    skip_rem = SKIP_CYCLES
                    print(f"    >> [GPU {gpu_id}] MAIN WINDOW bitti → skip-window={SKIP_CYCLES}\n")
                continue

            # ====== SKIP WINDOW ======
            if skip_rem > 0:
                bit_skip    = random.randrange(SKIP_BITS_MIN, SKIP_BITS_MAX+1)
                skip_amt    = 1 << bit_skip
                skip_start  = wrap_inc(last_main_start, skip_amt)
                start       = skip_start
                last_main_start = skip_start

                print(f"    >> [GPU {gpu_id}] [SKIP WINDOW] {SKIP_CYCLES-skip_rem+1}/{SKIP_CYCLES}: {bit_skip}-bit skip → 0x{start:x}")

                hit, addr, priv = scan_at(start, gpu_id)
                scan_ct += 1

                if hit and priv:
                    matched = next((p) for p in sorted_pfx if addr.startswith(p)) if addr else PREFIX
                    new_win = CONTINUE_MAP.get(matched, DEFAULT_CONTINUE)

                    if new_win > initial_window:
                        initial_window = new_win
                    window_rem = initial_window
                    skip_rem   = SKIP_CYCLES
                    start      = wrap_inc(start, BLOCK_SIZE)
                    print(f"    >> [GPU {gpu_id}] SKIP-HIT! matched={matched}, window={initial_window}\n")
                else:
                    skip_rem -= 1
                    if skip_rem == 0:
                        start = random_start_unique(gpu_id, used_starts, lock)
                        print(f"    >> [GPU {gpu_id}] SKIP WINDOW no-hit → random_start\n")
                continue

            # ====== DEFAULT CONTINUE ======
            for _ in range(DEFAULT_CONTINUE):
                hit, addr, priv = scan_at(start, gpu_id)
                scan_ct += 1
                if hit and priv:
                    matched        = next((p) for p in sorted_pfx if addr.startswith(p)) if addr else PREFIX
                    initial_window = CONTINUE_MAP.get(matched, DEFAULT_CONTINUE)
                    window_rem     = initial_window
                    start          = wrap_inc(start, BLOCK_SIZE)
                    print(f"    >> [GPU {gpu_id}] SEQ-HIT! matched={matched}, window={initial_window}\n")
                    break
                else:
                    start = wrap_inc(start, BLOCK_SIZE)
            else:
                start = random_start_unique(gpu_id, used_starts, lock)

            if scan_ct % 10 == 0:
                print(f"[GPU {gpu_id} STATUS] scans={scan_ct}, next=0x{start:x}")

    except KeyboardInterrupt:
        print(f"\n>> [GPU {gpu_id}] Çıkıyor...")

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    gpu_count = 2  # 2 GPU için ayarlandı
    manager = Manager()
    used_starts = manager.dict()  # set gibi kullanılacak: key=candidate, val=1
    lock = manager.Lock()

    workers = []
    for gpu_id in range(gpu_count):
        p = Process(target=worker, args=(gpu_id, used_starts, lock))
        p.start()
        workers.append(p)

    for p in workers:
        p.join()

if __name__ == "__main__":
    main()

