# Story: 1.3 EEPP Client V1

## Objective
Build a minimal async client to fetch active offers from EEPP and clarify the shape of the extraction flow.

## Scope
Includes:
- use HTTPX AsyncClient
- use timeout from /Users/folmedov/Dev/eepp/src/core/config.py
- implement fetch_postulacion(), fetch_evaluacion() and fetch_all()
- validate that the response is a list
- return a list of dictionaries with source, state and raw_data
- optionally include title, institution, region, city, url and salary_raw if directly from payload

Does not include:
- fingerprint
- persistence
- final schemas
- database integration
- matching with TEEE

## Definition of Done
A basic reusable client exists and can retrieve EEPP records in a form suitable for the next iteration.