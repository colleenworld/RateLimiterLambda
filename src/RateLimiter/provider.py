import boto3
from botocore.model import ServiceId
from botocore.signers import RequestSigner
from cachetools import TTLCache, cached
import os
import valkey
from valkey.credentials import CredentialProvider
from urllib.parse import ParseResult, urlencode, urlunparse


class Provider(CredentialProvider):
    def __init__(self, metrics=None):
        self.host = os.environ["ELASTICACHE_HOST"]
        self.cache_name = os.environ["CACHE_NAME"]
        self.user = os.environ["VALKEY_USER"]
        self.region = os.environ.get("AWS_REGION", "us-west-2")
        self.metrics = metrics

        session = boto3.Session()

        self.request_signer = RequestSigner(
            service_id= ServiceId("elasticache"),
            region_name=self.region,
            signing_name="elasticache",
            signature_version="v4",
            credentials=session.get_credentials(),
            event_emitter=session._session.get_component("event_emitter"),
        )

    @cached(cache=TTLCache(maxsize=128, ttl=900))
    def get_credentials(self):

        start = time.perf_counter()

        try:
            query_params = {
                "Action": "connect",
                "User": self.user,
                "ResourceType": "ServerlessCache"
            }

            url = urlunparse(
                ParseResult(
                    scheme="https",
                    netloc=self.cache_name,
                    path="/",
                    query=urlencode(query_params),
                    params="",
                    fragment="",
                )
            )

            signed_url = self.request_signer.generate_presigned_url(
                {
                    "method": "GET",
                    "url": url,
                    "body": {},
                    "headers": {},
                    "context": {}
                },
                operation_name="connect",
                expires_in=900,
                region_name=self.region,
            )

            if self.metrics:
                self.metrics.metric(
                    "IamCredentialGenerated",
                    1
                )

                self.metrics.metric(
                    "IamCredentialGenerationLatency",
                    (time.perf_counter() - start) * 1000,
                    "Milliseconds"
                )

            return (
                self.user,
                signed_url.removeprefix("https://")
            )

        except Exception:
            if self.metrics:
                self.metrics.metric(
                    "IamCredentialGenerationErrors",
                    1
                )

            raise

_client = None

def get_client():
    global _client

    if _client is None:
        _client = valkey.Valkey(
            host=os.environ["ELASTICACHE_HOST"],
            port=6379,
            ssl=True,
            credential_provider=Provider(),
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )

    return _client
