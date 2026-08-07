class RateLimiterError(Exception):
    pass

class ValkeyUnavailableError(RateLimiterError):
    pass

class ValkeyAuthenticationError(RateLimiterError):
    pass

class ConfigurationError(RateLimiterError):
    pass