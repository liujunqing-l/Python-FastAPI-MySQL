from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import httpx


def make_payload(index: int, sequence: int = 0) -> dict:
    imei = f"868488079852{index:06d}"
    return {
        "imei": imei,
        "message_type": 50,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "heart_rate": 70 + (index % 30),
        "blood_oxygen": 97,
        "body_temperature": 36.7,
        "wrist_temperature": 33.9,
        "diastolic": 80,
        "systolic": 120,
        "steps": sequence,
        "raw_hex": f"BDBDBDBD32{index:06X}{sequence:04X}",
    }


async def run(url: str, token: str, devices: int, burst: int) -> int:
    headers = {"X-Internal-Token": token}
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=10) as client:
        responses = await asyncio.gather(
            *(client.post("/api/v1/health", json=make_payload(i)) for i in range(devices)),
            return_exceptions=True,
        )
        failures = [r for r in responses if isinstance(r, Exception) or r.status_code not in (200, 201)]
        print(f"sent={len(responses)} failures={len(failures)}")
        if burst > 0:
            for batch in range(burst):
                result = await asyncio.gather(
                    *(client.post("/api/v1/health", json=make_payload(i, batch + 1)) for i in range(devices)),
                    return_exceptions=True,
                )
                failures.extend(r for r in result if isinstance(r, Exception) or r.status_code not in (200, 201))
            print(f"burst_batches={burst} total_failures={len(failures)}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--devices", type=int, default=200)
    parser.add_argument("--burst", type=int, default=1)
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.token, args.devices, args.burst))


if __name__ == "__main__":
    raise SystemExit(main())
