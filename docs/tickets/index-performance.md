# Index Performance Improvement Tickets

## Ticket 1: Parallel File Processing in IndexingService

### Summary
Process multiple files concurrently during indexing instead of sequentially.

### Current Behavior
Files are processed one at a time in `IndexingService.index_directory()`:
```python
async for file_path in self._file_walker.walk(...):
    async for result in self._process_file(file_path):
        # sequential processing
```

For 1,000 files, this means: read₁ → chunk₁ → save₁ → embed₁ → read₂ → chunk₂ → ...

### Proposed Behavior
Process N files concurrently using `asyncio.TaskGroup` or semaphore-bounded `asyncio.gather()`:
- Add `max_concurrent_files` parameter (default: 10)
- Use semaphore to limit concurrency and prevent resource exhaustion
- Maintain result ordering for deterministic output

### Impact
- **Expected speedup: 3-10x** depending on I/O vs CPU balance
- Embedding calls (the slowest step) can overlap with file reads and chunking
- Better utilization of thread pool for `to_thread()` wrapped operations

### Acceptance Criteria
- [ ] `IndexingService` accepts `max_concurrent_files` parameter
- [ ] Files are processed concurrently up to the configured limit
- [ ] `IndexingResult` totals remain accurate (thread-safe counters)
- [ ] Errors in one file don't abort processing of other files
- [ ] Unit tests verify concurrent execution (mock timing or call order)
- [ ] No regression in single-file behavior

### Implementation Notes
- Location: `src/txtsearch/services/index.py` lines 109-136
- Use `asyncio.Semaphore` to bound concurrency
- Consider `asyncio.TaskGroup` (Python 3.11+) for cleaner error handling
- Aggregate results after all tasks complete
- Watch for SQLite write contention—may need to serialize DB writes even if file processing is parallel

### Dependencies
None. This change is independent.

---

## Ticket 2: Batch Embeddings Across Multiple Files

### Summary
Accumulate chunks from multiple files and send to the embedding model in larger batches.

### Current Behavior
Each file's chunks are embedded separately in `VectorStore.add_documents()`:
```python
# Per file: 5-50 chunks embedded together
await self._vector_store.add_documents(ids, texts, metadatas)
```

A file with 10 chunks triggers one embedding call. 100 files = 100 embedding calls.

### Proposed Behavior
Buffer chunks across files and flush when batch size threshold is reached:
- Add `embedding_batch_size` parameter (default: 256)
- Accumulate chunks in memory until threshold
- Flush remaining chunks at end of indexing
- Decouple "save metadata" from "generate embeddings" timing

### Impact
- **Expected speedup: 2-5x** on embedding step
- Embedding models (sentence-transformers) are optimized for batch inference
- Reduces per-call overhead (model warm-up, memory allocation)
- Larger batches enable better GPU utilization if available

### Acceptance Criteria
- [ ] `IndexingService` accepts `embedding_batch_size` parameter
- [ ] Chunks are buffered and flushed at threshold
- [ ] Final flush occurs after all files processed (no orphaned chunks)
- [ ] Metadata is still saved per-file (maintains consistency)
- [ ] Memory usage is bounded by batch size
- [ ] Unit tests verify batching behavior with mock VectorStore

### Implementation Notes
- Location: `src/txtsearch/services/index.py`
- Create internal buffer: `list[tuple[str, str, dict]]` for (id, text, metadata)
- Add `_flush_embedding_batch()` helper method
- Call flush when `len(buffer) >= batch_size` or at method exit
- Use `try/finally` to ensure flush on error
- Consider: if a flush fails, should we retry or skip those chunks?

### Dependencies
- **Interacts with Ticket 1**: If files are processed in parallel, the chunk buffer needs thread-safe access (use `asyncio.Lock`)
- Recommend implementing Ticket 1 first, then adding batching with proper synchronization

---

## Ticket 3: Single Directory Walk with Pattern Filtering

### Summary
Replace multiple `rglob()` calls with a single directory traversal and in-memory pattern matching.

### Current Behavior
`FileWalker.walk()` iterates through include patterns sequentially:
```python
for pattern in self._include_patterns:
    for path in await asyncio.to_thread(lambda: list(directory.rglob(pattern))):
        # filter and yield
```

With 8 default patterns, this walks the directory tree 8 times.

### Proposed Behavior
Walk directory once with `rglob("*")` or `os.walk()`, then filter:
```python
all_files = await asyncio.to_thread(lambda: list(directory.rglob("*")))
for path in all_files:
    if any(path.match(p) for p in include_patterns):
        if not any(path.match(p) for p in exclude_patterns):
            yield path
```

### Impact
- **Expected speedup: 1.5-3x** on file discovery phase
- Single filesystem traversal instead of N traversals
- More consistent performance regardless of pattern count
- Eliminates potential duplicate file discovery if patterns overlap

### Acceptance Criteria
- [ ] Directory is traversed exactly once regardless of pattern count
- [ ] Include/exclude pattern matching produces identical results to current behavior
- [ ] Files are still filtered correctly (no false positives/negatives)
- [ ] Performance improves for multi-pattern scenarios
- [ ] Unit tests cover: single pattern, multiple patterns, overlapping patterns, exclude patterns
- [ ] Edge cases handled: symlinks, permission errors, empty directories

### Implementation Notes
- Location: `src/txtsearch/services/file_walker.py`
- Use `Path.match()` for glob-style matching or `fnmatch.fnmatch()` for explicit control
- Consider using `os.scandir()` for even better performance (avoids stat calls)
- Pre-compile patterns if using regex alternative
- Watch for memory usage on very large directories (100k+ files)—may need to stream results

### Dependencies
None. This change is independent and can be implemented/tested in isolation.

---

## Recommended Implementation Order

1. **Ticket 3** (Single Directory Walk) - Lowest risk, isolated change, easy to verify
2. **Ticket 1** (Parallel File Processing) - Highest impact, moderate complexity
3. **Ticket 2** (Batch Embeddings) - Builds on Ticket 1, requires synchronization

Each ticket can be merged independently, but Ticket 2's implementation should account for concurrency introduced by Ticket 1.
