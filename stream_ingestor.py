import asyncio
import logging
import time
from typing import Dict, Any, Callable, Awaitable, List

# Assume a shared utility for configuration and data models
# from .config import AppConfig
# from .data_models import RawOSINTEvent

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RateLimiter:
    """Manages API call rates to prevent exceeding service limits."""
    def __init__(self, requests_per_period: int, period_seconds: int):
        self.requests_per_period = requests_per_period
        self.period_seconds = period_seconds
        self._timestamps: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            # Remove timestamps older than the period
            self._timestamps = [ts for ts in self._timestamps if ts > now - self.period_seconds]

            if len(self._timestamps) >= self.requests_per_period:
                # Calculate time until the oldest request in the current window expires
                wait_time = self.period_seconds - (now - self._timestamps[0])
                logger.warning(f"Rate limit hit. Waiting for {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time + 0.1)  # Add a small buffer
                # Re-evaluate after waiting
                return await self.acquire()
            else:
                self._timestamps.append(time.monotonic())


class OSINTStreamIngestor:
    """Manages the ingestion of raw OSINT data from various external sources.
    
    This component is responsible for connecting to APIs, parsing initial responses,
    applying source-specific rate limits, and pushing raw event data into a 
    processing queue for subsequent enrichment and analysis.
    """
    def __init__(
        self, 
        processing_queue: asyncio.Queue,
        source_configs: Dict[str, Dict[str, Any]],
        global_rate_limit_rps: int = 5
    ):
        self.processing_queue = processing_queue
        self.source_configs = source_configs
        self.global_rate_limiter = RateLimiter(global_rate_limit_rps, 1) # 5 requests per second global
        self._source_specific_limiters: Dict[str, RateLimiter] = {}
        self._ingest_tasks: List[asyncio.Task] = []

        # Initialize source-specific rate limiters
        for source_name, config in source_configs.items():
            rps = config.get('rate_limit_rps', 1) # Default to 1 rps if not specified
            period = config.get('rate_limit_period_seconds', 1)
            self._source_specific_limiters[source_name] = RateLimiter(rps, period)
            logger.info(f"Initialized rate limiter for '{source_name}': {rps} reqs/{period}s")

    async def _fetch_data_from_source(self, source_name: str, endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Simulates fetching data from a given OSINT source endpoint."""
        await self.global_rate_limiter.acquire()
        await self._source_specific_limiters[source_name].acquire()

        logger.debug(f"Fetching from {source_name}:{endpoint} with params {params}")
        # In a real system, this would involve HTTP requests, API calls, or database queries.
        # For demonstration, we'll simulate a network delay and return mock data.
        await asyncio.sleep(0.5 + 0.5 * (hash(source_name + endpoint) % 10) / 10) # Simulate variable network delay
        
        # Mock data based on source and endpoint
        if "twitter" in source_name:
            return [{
                "id": f"tweet_{time.time()}_{i}",
                "source": source_name,
                "content": f"Sample tweet from {source_name} about {params.get('query', 'OSINT')} #{i}",
                "timestamp": time.time(),
                "author": "user_xyz"
            } for i in range(1 + (hash(endpoint) % 3))]
        elif "rss" in source_name:
            return [{
                "id": f"rss_item_{time.time()}_{i}",
                "source": source_name,
                "title": f"Article Title {i} from {source_name}",
                "link": f"http://example.com/article/{i}",
                "published": time.time(),
                "summary": "This is a summary of an important article."
            } for i in range(1 + (hash(endpoint) % 2))]
        else:
            return [{
                "id": f"generic_item_{time.time()}_{i}",
                "source": source_name,
                "data": f"Generic data point {i} from {source_name}",
                "ts": time.time()
            } for i in range(1)]

    async def _ingest_source(self, source_name: str, config: Dict[str, Any]):
        """Continuously ingests data from a single OSINT source based on its configuration."""
        logger.info(f"Starting ingestion for source: {source_name}")
        endpoints = config.get('endpoints', [])
        poll_interval = config.get('poll_interval_seconds', 60)

        while True:
            try:
                for endpoint_config in endpoints:
                    endpoint_url = endpoint_config.get('url')
                    params = endpoint_config.get('params', {})
                    
                    if not endpoint_url:
                        logger.warning(f"Source '{source_name}' has an endpoint with no URL. Skipping.")
                        continue

                    raw_events = await self._fetch_data_from_source(source_name, endpoint_url, params)
                    for event_data in raw_events:
                        # In a real system, RawOSINTEvent would be a Pydantic model
                        # raw_event = RawOSINTEvent(source=source_name, timestamp=time.time(), data=event_data)
                        # await self.processing_queue.put(raw_event)
                        await self.processing_queue.put({
                            "source": source_name,
                            "timestamp": time.time(),
                            "data": event_data
                        })
                        logger.debug(f"Put raw event from {source_name} into queue.")

            except asyncio.CancelledError:
                logger.info(f"Ingestion for source '{source_name}' cancelled.")
                break
            except Exception as e:
                logger.error(f"Error ingesting from source '{source_name}': {e}", exc_info=True)
            
            logger.debug(f"Source '{source_name}' waiting for {poll_interval} seconds before next poll.")
            await asyncio.sleep(poll_interval)

    async def start(self):
        """Starts all configured source ingestion tasks concurrently."""
        logger.info("OSINT Stream Ingestor starting...")
        for source_name, config in self.source_configs.items():
            task = asyncio.create_task(self._ingest_source(source_name, config))
            self._ingest_tasks.append(task)
        
        await asyncio.gather(*self._ingest_tasks)

    async def stop(self):
        """Gracefully stops all running ingestion tasks."""
        logger.info("OSINT Stream Ingestor stopping...")
        for task in self._ingest_tasks:
            task.cancel()
        await asyncio.gather(*self._ingest_tasks, return_exceptions=True) # Wait for tasks to finish cancelling
        logger.info("OSINT Stream Ingestor stopped.")


# Example Usage (for testing purposes)
async def main():
    # This queue would typically be passed from a central application orchestrator
    shared_processing_queue = asyncio.Queue()

    # Example configuration for various OSINT sources
    osint_sources_config = {
        "twitter_feed_a": {
            "endpoints": [
                {"url": "/api/v1/tweets/search", "params": {"query": "cybersecurity"}},
                {"url": "/api/v1/tweets/trends", "params": {"location": "global"}}
            ],
            "rate_limit_rps": 2, # 2 requests per second for this source
            "poll_interval_seconds": 10
        },
        "rss_news_b": {
            "endpoints": [
                {"url": "http://example.com/rss/security", "params": {}},
                {"url": "http://another.com/rss/intel", "params": {}}
            ],
            "rate_limit_rps": 1, # 1 request per second for this source
            "poll_interval_seconds": 20
        },
        "web_scrape_c": {
            "endpoints": [
                {"url": "http://public-forum.org/latest", "params": {"category": "threats"}}
            ],
            "rate_limit_rps": 0.5, # 1 request every 2 seconds
            "rate_limit_period_seconds": 2,
            "poll_interval_seconds": 30
        }
    }

    ingestor = OSINTStreamIngestor(shared_processing_queue, osint_sources_config, global_rate_limit_rps=3)
    ingestor_task = asyncio.create_task(ingestor.start())

    # Simulate a consumer for the processing queue
    async def consumer():
        logger.info("Consumer started.")
        processed_count = 0
        while True:
            try:
                raw_event = await asyncio.wait_for(shared_processing_queue.get(), timeout=5.0)
                processed_count += 1
                logger.info(f"Consumed event from {raw_event['source']}. Total processed: {processed_count}")
                # In a real system, this would pass to a transformer or analyzer
                shared_processing_queue.task_done()
            except asyncio.TimeoutError:
                logger.info("Consumer: No items in queue for 5 seconds. Exiting.")
                break
            except Exception as e:
                logger.error(f"Consumer error: {e}", exc_info=True)
                break

    consumer_task = asyncio.create_task(consumer())

    # Let it run for a while
    await asyncio.sleep(60)

    logger.info("Shutting down ingestor and consumer...")
    await ingestor.stop()
    await consumer_task
    logger.info("Application shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user.")
