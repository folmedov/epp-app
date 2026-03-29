# Development Approach

This document describes how the project should be delivered and refined over time.

- `requirement.md` is the source of truth for sprint scope and status.
- `architecture.md` is the source of truth for the target technical design.
- This document defines the evolutionary delivery approach used to move from discovery to a stable implementation.

## 1. Project Goal
This project aims to build an ETL pipeline that synchronizes job offers from EEPP and TEEE into PostgreSQL for tracking and analysis.

The implementation is intentionally iterative. Early iterations prioritize discovery, validation of data flow, and reduction of uncertainty. Later iterations refine schemas, robustness, observability, matching logic, and persistence behavior based on findings gathered during earlier stages.

## 2. Delivery Approach
This project follows an evolutionary and iterative approach.

Each sprint should deliver a usable increment, but not necessarily the final or fully hardened version of a component.

In the first stage, the focus is:
* Discovering real source behavior
* Validating the end to end data flow
* Creating minimal working versions of the extractor, models, and processing logic

In later stages, the focus shifts to:
* Contract stabilization
* Stronger validation
* Retry and error handling improvements
* Idempotent persistence
* Cross source matching and lifecycle tracking

The goal is not to fully harden every module from the beginning, but to evolve the implementation based on validated behavior from real data sources.

## 3. Current Delivery Focus
The current phase of the project is Sprint 1, which focuses on building the first EEPP vertical slice.

The goal of this phase is to clarify and prove the basic flow:
1. discover the EEPP source behavior;
2. extract active EEPP offers;
3. define the first internal data shape;
4. prepare the path toward fingerprinting and loading.

This means early components may be intentionally simple as long as they help validate the real flow of data through the system.

## 4. Current Iteration Principles
* Prefer simple working implementations over premature abstraction.
* Validate the real behavior of sources before stabilizing internal contracts.
* Keep early components small and replaceable.
* Refine schemas and processing rules after observing real data edge cases.
* Keep V1 components compatible with the target architecture, even if they do not implement the full contract yet.

## 5. Data Flow
Target flow:
1. Extraction: fetch active offers from EEPP.
2. Transformation: clean values and compute fingerprint.
3. Persistence: perform idempotent upserts into PostgreSQL.

In early iterations, the flow may stop before the final persistence contract is fully hardened. This is acceptable if the iteration improves clarity about source behavior or internal data shape.

## 6. Guiding Rules
* Identity: fingerprint is the deduplication key. The exact fingerprint composition may be refined as source behavior and matching edge cases become clearer.
* Source Priority: EEPP is the master source for active salary data.
* Audit: every record must preserve the original source payload in `raw_data`.

