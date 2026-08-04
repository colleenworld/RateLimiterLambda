import asyncio
import os
from collections import Counter
import httpx

CONCURRENT_REQUESTS = 6
CUSTOMER_ID = "burst-test-customer"

async def send_request(client, api_url, start_event):
    # Hold all tasks here until every request is ready.
    await start_event.wait()

    try:
        response = await client.post(
            api_url,
            json={
                "customer_id": CUSTOMER_ID,
            },
        )

        return {
            "status": response.status_code,
            "body": response.text,
        }

    except Exception as error:
        return {
            "status": "exception",
            "body": repr(error),
        }


async def run_burst():
    api_url = os.environ["API_URL"]

    start_event = asyncio.Event()

    async with httpx.AsyncClient(
        timeout=10.0,
    ) as client:

        tasks = [
            asyncio.create_task(
                send_request(
                    client,
                    api_url,
                    start_event,
                )
            )
            for _ in range(CONCURRENT_REQUESTS)
        ]

        # All tasks have now been created.
        # Release them at approximately the same time.
        start_event.set()

        return await asyncio.gather(*tasks)


def main():
    results = asyncio.run(run_burst())

    counts = Counter(
        result["status"]
        for result in results
    )

    print("\nBurst test results")
    print("==================")
    print(f"Requests:   {CONCURRENT_REQUESTS}")
    print(f"200:        {counts[200]}")
    print(f"429:        {counts[429]}")
    print(f"500:        {counts[500]}")
    print(f"503:        {counts[503]}")
    print(f"Exceptions: {counts['exception']}")

    unexpected = [
        result
        for result in results
        if result["status"] not in (200, 429)
    ]

    if unexpected:
        print("\nUnexpected responses:")

        for result in unexpected:
            print(
                f"{result['status']}: "
                f"{result['body']}"
            )

    assert counts[500] == 0, (
        f"Received {counts[500]} internal server errors"
    )

    assert counts[503] == 0, (
        f"Received {counts[503]} service unavailable responses"
    )

    assert counts["exception"] == 0, (
        f"Received {counts['exception']} client exceptions"
    )

    assert counts[200] + counts[429] == CONCURRENT_REQUESTS

    print("\nPASS: all requests were handled as 200 or 429")

if __name__ == "__main__":
    main()