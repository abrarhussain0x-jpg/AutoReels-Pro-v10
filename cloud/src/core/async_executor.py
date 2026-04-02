"""Async/concurrent execution engine for high-performance video processing."""

import asyncio
import logging
from typing import List, Callable, Any, Optional
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import time

log = logging.getLogger(__name__)


class AsyncExecutor:
    """High-performance async executor with connection pooling."""

    def __init__(self, max_workers: int = 8, executor_type: str = "thread"):
        """
        Initialize async executor.
        
        Args:
            max_workers: Maximum concurrent workers
            executor_type: 'thread' or 'process' based on task type
        """
        self.max_workers = max_workers
        self.executor_type = executor_type
        
        if executor_type == "process":
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
        else:
            self.executor = ThreadPoolExecutor(max_workers=max_workers)

    async def batch_execute(
        self,
        tasks: List[tuple],
        batch_size: int = 10,
        timeout: Optional[float] = None
    ) -> List[Any]:
        """
        Execute tasks in batches with concurrency control.
        
        Args:
            tasks: List of (func, args, kwargs) tuples
            batch_size: Number of concurrent tasks
            timeout: Task timeout in seconds (applied to each task)
            
        Returns:
            List of results in original order
        """
        if not tasks:
            return []
            
        start = time.time()
        results = []
        
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            futures = [
                asyncio.get_event_loop().run_in_executor(
                    self.executor, 
                    self._run_task, 
                    func, 
                    args, 
                    kwargs
                )
                for func, args, kwargs in batch
            ]
            
            try:
                # Apply timeout if specified
                if timeout:
                    batch_results = await asyncio.wait_for(
                        asyncio.gather(*futures, return_exceptions=True),
                        timeout=timeout
                    )
                else:
                    batch_results = await asyncio.gather(*futures, return_exceptions=True)
                results.extend(batch_results)
            except asyncio.TimeoutError:
                log.error(f"[AsyncExecutor] Batch timeout after {timeout}s")
                raise
            except Exception as e:
                log.error(f"[AsyncExecutor] Batch execution failed: {e}")
                raise
                
        elapsed = time.time() - start
        log.info(f"[AsyncExecutor] Processed {len(tasks)} tasks in {elapsed:.2f}s")
        
        return results

    @staticmethod
    def _run_task(func: Callable, args: tuple, kwargs: dict) -> Any:
        """Execute a single task."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.error(f"Task failed: {e}")
            raise

    def shutdown(self):
        """Clean up executor resources."""
        self.executor.shutdown(wait=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()


class BatchProcessor:
    """Batch processing for API calls (e.g., Claude batch requests)."""

    def __init__(self, batch_size: int = 100, max_concurrent: int = 5):
        """
        Initialize batch processor.
        
        Args:
            batch_size: Items per batch
            max_concurrent: Max concurrent API calls
        """
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent

    async def process_batches(
        self,
        items: List[Any],
        handler: Callable,
        **kwargs
    ) -> List[Any]:
        """
        Process items in batches with concurrency control.
        
        Args:
            items: List of items to process
            handler: Async callable that processes a batch
            **kwargs: Additional arguments to pass to handler
            
        Returns:
            Flattened list of all results
        """
        if not items:
            return []
            
        results = []
        
        for i in range(0, len(items), self.batch_size):
            batch = items[i:i+self.batch_size]
            batch_num = i // self.batch_size + 1
            log.info(f"[BatchProcessor] Processing batch {batch_num} ({len(batch)} items)")
            
            try:
                batch_results = await handler(batch, **kwargs)
                results.extend(batch_results if isinstance(batch_results, list) else [batch_results])
            except Exception as e:
                log.error(f"[BatchProcessor] Batch {batch_num} failed: {e}")
                raise
            
        return results


# Singleton executor instance
_executor: Optional[AsyncExecutor] = None


def get_async_executor() -> AsyncExecutor:
    """Get or create global async executor."""
    global _executor
    if _executor is None:
        _executor = AsyncExecutor(max_workers=8, executor_type="thread")
    return _executor
