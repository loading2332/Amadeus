# memU-Inspired Summary Index Dossier

## Strategy Identity

This strategy represents memU's hierarchical memory catalog: resources, memory
items, and category summaries used as a navigation layer for staged retrieval.

Primary evidence:

- `/Users/didi/develop/memoryresearch/memU/README.md:230` to `:240`
- `/Users/didi/develop/memoryresearch/memU/README.md:407` to `:463`
- `/Users/didi/develop/memoryresearch/memU/src/memu/database/models.py:12`
  to `:134`
- `/Users/didi/develop/memoryresearch/memU/src/memu/app/retrieve.py:570`
  to `:784`
- `/Users/didi/develop/memoryresearch/memU/src/memu/app/crud.py:538`
  to `:683`

Evidence level: A.

Reason: README architecture, data models, retrieval pipeline, and update
propagation code all support the same resource -> item -> category design.

## Original System Data Flow

```text
memorize(resource)
-> store resource metadata
-> extract memory items
-> categorize items
-> create/update category summaries

retrieve(query)
-> decide whether retrieval is needed
-> route query to category summaries
-> check whether category content is sufficient
-> rank items within selected categories or referenced ids
-> check whether item content is sufficient
-> retrieve resources if needed
-> return categories, items, resources

patch item
-> update/delete item
-> relink categories
-> patch affected category summaries
```

## Core Mechanisms

1. Category summaries are a navigation index.

   A category is not merely a tag. Its summary can route a query before item or
   resource retrieval happens.

2. Retrieval is staged.

   memU can stop after category-level information, drill down to items, or drill
   down again to resources depending on sufficiency.

3. Query can evolve between stages.

   The LLM retrieval path can rewrite the active query after checking retrieved
   content.

4. Items and resources remain separate.

   Items are extracted memory units. Resources are original source material.
   The system can answer from items or go back to the resource layer when
   needed.

5. Category summaries are maintained.

   Updates and deletes can propagate patches to affected category summaries.

## Non-Omittable Mechanisms

The Amadeus prototype stops being memU-inspired if it omits these:

- A separate category summary layer exists above items.
- Retrieval starts by routing through category summaries.
- The adapter can stop early when category or item evidence is sufficient.
- Item retrieval is constrained or guided by selected categories/references.
- The trace exposes category, item, and resource stages separately.
- Updates to items can affect category summaries in lifecycle tests.

## Omittable In The First Version

These can be deferred because fixed artifacts are used:

- Full `memorize()` resource ingestion pipeline.
- Multimodal resources.
- Fully LLM-based sufficiency and query rewriting.
- Configurable workflow engine.
- Proactive context loading and background monitoring.
- Real category patch prompts, unless lifecycle eval is enabled.

## Minimal Prototype Definition

For fixed memory artifacts, the memU adapter should:

```text
1. Accept artifacts as resources and/or already extracted items.
2. Build categories with summary text.
3. Link items to categories.
4. Route each query to category summaries first.
5. Decide whether category evidence is sufficient.
6. If needed, retrieve items from selected categories.
7. Decide whether item evidence is sufficient.
8. If needed, retrieve source resources.
9. Return staged hits and injection context.
```

The first version may use deterministic sufficiency rules. If it does, the trace
must say so.

## Fidelity Checklist

- [ ] A query can match a category summary even when no single item text has the
      same lexical wording.
- [ ] A category-level sufficient answer stops before item/resource retrieval.
- [ ] An item-level sufficient answer stops before resource retrieval.
- [ ] Item retrieval is narrowed by selected categories or references.
- [ ] The trace lists category hits, item hits, resource hits, and stop reason.
- [ ] A lifecycle test can update an item and observe the affected category
      summary changing.
- [ ] Category summaries are not treated as the final source of truth when item
      or resource evidence is required.

## Conclusion Boundary

If this prototype performs well, Amadeus can claim that summary-as-navigation
and staged drilldown improve memory use for the evaluated tasks.

It cannot claim that memU's full continuous learning pipeline, multimodal
resource handling, proactive retrieval, or LLM sufficiency behavior is validated
until those parts are explicitly implemented and scored.

