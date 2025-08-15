import subprocess
import random
import threading
import time

# Ayarlar
PREFIX = "1PWo3JeB"
RANGE_SIZE = 40
LOWER_BOUND = 0x400000000000000000
UPPER_BOUND = 0x7FFFFFFFFFFFFFFFFF
FOUND_FILE = "ALL.txt"

def run_gpu_process(gpu_id):
    print(f"🎯 GPU {gpu_id} başlatılıyor (range: {hex(LOWER_BOUND)} – {hex(UPPER_BOUND)})...")

    while True:
        # Rastgele başlangıç değeri üret
        max_start = UPPER_BOUND - (1 << RANGE_SIZE)
        random_start = hex(random.randint(LOWER_BOUND, max_start))[2:].upper()

        print(f"🚀 GPU {gpu_id} – tarama: {random_start} (2^{RANGE_SIZE})")

        # vanitysearch komutunu çalıştır
        cmd = [
            "./vanitysearch",
            "-gpuId", str(gpu_id),
            "-o", FOUND_FILE,
            "-start", random_start,
            "-range", str(RANGE_SIZE),
            PREFIX
        ]

        try:
            subprocess.run(cmd, check=True)
            print(f"✅ GPU {gpu_id} tamamladı: {random_start}")
        except subprocess.CalledProcessError as e:
            print(f"❌ GPU {gpu_id} hata aldı: {e}")

        print("----------------------------")
        time.sleep(0.5)  # Sistem çok hızlı dönmesin diye küçük gecikme

# Thread’leri başlat
threads = []
for gpu_id in [0, 1]:
    t = threading.Thread(target=run_gpu_process, args=(gpu_id,))
    t.daemon = True
    t.start()
    threads.append(t)

# Ana thread'i çalışır halde tut
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("⛔ Program kullanıcı tarafından durduruldu.")
