"""
Enhanced retry middleware with exponential backoff.
"""

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message
import time


class EnhancedRetryMiddleware(RetryMiddleware):
    """Retry middleware with exponential backoff and better logging."""

    def process_response(self, request, response, spider):
        if request.meta.get("dont_retry", False):
            return response

        if response.status in self.retry_http_codes:
            reason = response_status_message(response.status)
            retry_times = request.meta.get("retry_times", 0) + 1

            # Exponential backoff
            delay = min(2**retry_times, 60)  # Max 60 seconds
            spider.logger.warning(
                f"Retrying {request.url} (attempt {retry_times}/{self.max_retry_times}) "
                f"after {delay}s delay. Reason: {reason}"
            )

            time.sleep(delay)
            return self._retry(request, reason, spider) or response

        return response
