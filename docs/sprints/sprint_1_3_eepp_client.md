# Story: 1.3 EEPP Client V1

## Objective
Build a minimal async client to fetch active offers from EEPP and clarify the shape of the extraction flow.

## Scope
Includes:
* fetch postulacion and evaluacion endpoints
* confirm list based responses
* attach source state to each record
* preserve the original payload

Does not include:
* final internal schema design
* fingerprint generation
* persistence
* advanced retry strategy
* final observability contract

## Definition of Done
A basic reusable client exists and can retrieve EEPP records in a form suitable for the next iteration.