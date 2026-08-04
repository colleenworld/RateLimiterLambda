from locust import HttpUser, task, between

class RateLimiterUser(HttpUser):
    wait_time = between(0, 0)

    @task
    def check_rate_limit(self):
        with self.client.post(
            "/v1/check",
            json={
                "customer_id": "load-test-customer",
            },
            catch_response=True,
        ) as response:

            if response.status_code == 200:
                response.success()

            elif response.status_code == 429:
                # This is expected rate-limiter behavior,
                # not a load-test failure.
                response.success()

            else:
                response.failure(
                    f"Unexpected status: {response.status_code}"
                )