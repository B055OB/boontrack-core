import asyncio
import time
from app.services.ai_gateway import AIGateway

# Dataset 100 Sample Kueri Uji
SAMPLE_QUERIES = [
    ("saya baru lulus mau kerja", "GET_JOB", "FIND_JOB"),
    ("cara bikin cv ats friendly", "GET_JOB", "CREATE_CV"),
    ("tips wawancara kerja fresh graduate", "GET_JOB", "PREPARE_INTERVIEW"),
    ("contoh surat lamaran kerja bahasa inggris", "GET_JOB", "WRITE_COVER_LETTER"),
    ("cara negosiasi gaji pertama", "GET_JOB", "NEGOTIATE_SALARY"),
    ("optimasi profil linkedin biar di-hiring", "GET_JOB", "BUILD_LINKEDIN"),
] * 17  # Diulang hingga ~100 sampel

async def run_benchmark():
    gateway = AIGateway()
    correct_goals = 0
    correct_intents = 0
    total_time = 0
    total = len(SAMPLE_QUERIES)

    print(f"\n⚡ Memulai Benchmark Evaluasi ({total} Kueri)...\n")

    start_all = time.time()
    for query, exp_goal, exp_intent in SAMPLE_QUERIES:
        t0 = time.time()
        res = await gateway.detect_goal_and_intent(query)
        latency = (time.time() - t0) * 1000
        total_time += latency

        if res["goal"] == exp_goal:
            correct_goals += 1
        if res["intent"] == exp_intent:
            correct_intents += 1

    total_duration = time.time() - start_all
    goal_acc = (correct_goals / total) * 100
    intent_acc = (correct_intents / total) * 100
    avg_latency = total_time / total

    print("=" * 45)
    print("📊 HASIL BENCHMARK AI GOAL DETECTOR")
    print("=" * 45)
    print(f"Total Test Query : {total}")
    print(f"Goal Accuracy    : {goal_acc:.2f}%")
    print(f"Intent Accuracy  : {intent_acc:.2f}%")
    print(f"Avg Latency      : {avg_latency:.2f} ms")
    print(f"Total Duration   : {total_duration:.2f} detik")
    print("=" * 45 + "\n")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
