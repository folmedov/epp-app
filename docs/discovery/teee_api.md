# Discovery: trabajaenelestado.cl API

The portal use Elasticsearch as backend, exposing a search endpoint at `https://elastic.serviciocivil.cl/listado_teee/_doc/_search` that accepts POST requests with a JSON body containing the search query. The response includes job offers in a similar structure to EEPP, but with some differences in field names and values.

## Endpoint Information
* Portal endpoint: https://elastic.serviciocivil.cl/listado_teee/_doc/_search
* Method: POST

## Payload Structure

### Status: Postulacion

```json
{
    "from": 0,
    "size": "36",
    "sort":
        [
            {
                "_script": {
                    "type": "number",
                    "script":
                        {
                            "lang": "painless",
                            "source": "if(params.scores.containsKey(doc['Estado.keyword'].value)) { 
                                    return (params.scores[doc['Estado.keyword'].value] * _score);
                                } 
                                return (0.1 * _score);",
                            "params": {
                                "scores": {
                                    "postulacion": 1.5,
                                    "evaluacion": 1.1,
                                    "finalizadas": 1
                                }
                            }
                        },
                    "order": "desc"
                }
            },
            {
                "Datesum": "asc"
            }
        ],
        "track_scores": true,
        "query": {
            "bool": {
                "must": [
                    {
                        "term": {
                            "Estado":"postulacion"
                        }
                    }
                ]
            }
        }
    }
```

#### Response Structure

```json
{
    "took": 5,
    "timed_out": false,
    "_shards": {
        "total": 5,
        "successful": 5,
        "skipped": 0,
        "failed": 0
    },
    "hits": {
        "total": 258,
        "max_score": 5.12593,
        "hits": [
            {
                "_index": "listado_teee",
                "_type": "_doc",
                "_id": "EEPP_postulacion 085",
                "_score": 5.12593,
                "_source": {
                    "ID Conv": "138411",
                    "Datesum": 753797,
                    "Datesum Inicio": 753790,
                    "Ministerio": "Ministerio de Seguridad Pública",
                    "Cargo": "Profesional para Equipo de Detección Temprana",
                    "Area de Trabajo": "Area para cumplir misión institucional",
                    "Fecha inicio Convocatoria": "25/03/2026 0:00:00",
                    "Fecha cierre Convocatoria": "01/04/2026 17:00:00",
                    "URL": "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=138411&c=0&j=0&tipo=convpostularavisoTrabajo",
                    "Region": "Región de Los Lagos",
                    "Ciudad": "Castro",
                    "Institucion/Entidad": "Subsecretaría de Prevención del Delito /  ",
                    "Tipo Convocatoria": "EEPP",
                    "Origen": "Listado",
                    "Estado": "postulacion",
                    "Tipo Postulacion": "Postulacion en linea",
                    "Cargo Profesional": "Profesionales",
                    "Codigo Cargo Profesional": "cargo1",
                    "Codigo Area Interes": "area19",
                    "Codigo Region": "region10",
                    "Ganador": ""
                },
                "sort": [
                    7.688894748687744,
                    753797
                ]
            },
            // More offers...
        ]
    }
}
```

### Status: Evaluacion

```json
{
    "from": 0,
    "size": "36",
    "sort": [
        {
            "_script": {
                "type": "number",
                "script": {
                    "lang": "painless",
                    "source": "if(params.scores.containsKey(doc['Estado.keyword'].value)) { return (params.scores[doc['Estado.keyword'].value] * _score);} return (0.1 * _score);",
                    "params": {
                        "scores": {
                            "postulacion": 1.5,
                            "evaluacion": 1.1,
                            "finalizadas": 1
                        }
                    }
                },
                "order": "desc"
            }
        },
        {
            "Datesum": "asc"
        }
    ],
    "track_scores": true,
    "query": {
        "bool": {
            "must": [
                {
                    "term": {
                        "Estado": "evaluacion"
                    }
                }
            ]
        }
    }
}
```

#### Response:

```json
{
    "took": 2,
    "timed_out": false,
    "_shards": {
        "total": 5,
        "successful": 5,
        "skipped": 0,
        "failed": 0
    },
    "hits": {
        "total": 1211,
        "max_score": 3.926237,
        "hits": [
            {
                "_index": "listado_teee",
                "_type": "_doc",
                "_id": "DIRECTORES_evaluacion 305",
                "_score": 3.926237,
                "_source": {
                    "ID Conv": "",
                    "Datesum": 750168,
                    "Datesum Inicio": 750116,
                    "Ministerio": "ILUSTRE MUNICIPALIDAD DE PENCAHUE",
                    "Cargo": "Jefe DAEM",
                    "Area de Trabajo": "Educación /Docencia /Capacitación",
                    "Fecha inicio Convocatoria": "09/05/2016 0:00:00",
                    "Fecha cierre Convocatoria": "30/06/2016 17:30:00",
                    "URL": "https://directoresparachile.cl/Repositorio/PDFConcursos/dee_69110800.pdf?director-establecimiento-municipal-concurso-jefe-daem",
                    "Region": "Región del Maule",
                    "Ciudad": "Pencahue",
                    "Institucion/Entidad": "CONCURSO JEFE DAEM",
                    "Tipo Convocatoria": "DEE",
                    "Origen": "Listado",
                    "Estado": "evaluacion",
                    "Tipo Postulacion": "",
                    "Cargo Profesional": "Profesionales Educación",
                    "Codigo Cargo Profesional": "cargo7",
                    "Codigo Area Interes": "area11",
                    "Codigo Region": "region7",
                    "Ganador": ""
                },
                "sort": [
                    4.318860816955567,
                    750168
                ]
            },
            // More offers...
        ]
    }
}
```


### Status: Finalizado

```json
{
    "from": 0,
    "size": "36",
    "sort": [
        {
            "_script": {
                "type": "number",
                "script": {
                    "lang": "painless",
                    "source": "if(params.scores.containsKey(doc['Estado.keyword'].value)) { return (params.scores[doc['Estado.keyword'].value] * _score);} return (0.1 * _score);",
                    "params": {
                        "scores": {
                            "postulacion": 1.5,
                            "evaluacion": 1.1,
                            "finalizadas": 1
                        }
                    }
                },
                "order": "desc"
            }
        },
        {
            "Datesum": "asc"
        }
    ],
    "track_scores": true,
    "query": {
        "bool": {
            "must": [
                {
                    "term": {
                        "Estado": "finalizadas"
                    }
                }
            ]
        }
    }
}
```

#### Response:

```json
{
    "took": 19,
    "timed_out": false,
    "_shards": {
        "total": 5,
        "successful": 5,
        "skipped": 0,
        "failed": 0
    },
    "hits": {
        "total": 48769,
        "max_score": 0.039070927,
        "hits": [
            {
                "_index": "listado_teee",
                "_type": "_doc",
                "_id": "EEPP_JUNJI_finalizadas 3187",
                "_score": 0.039070927,
                "_source": {
                    "ID Conv": 18271,
                    "Datesum": 707021,
                    "Datesum Inicio": 753513,
                    "Ministerio": "Ministerio de Educación",
                    "Cargo": "Técnico/a en Educación de Párvulos Extensión Horaria, Llanquihu – Osorno Región de Los Lagos",
                    "Area de Trabajo": "Area para cumplir misión institucional",
                    "Fecha inicio Convocatoria": "27/06/2025 01:00:00",
                    "Fecha cierre Convocatoria": "04/07/1900 01:41:45",
                    "URL": "https://junji.myfront.cl/oferta-de-empleo/18271/tecnicoa-en-educacion-de-parvulos-extension-horaria-provincia-de-llanquihue-osorno-region-de-los/",
                    "Region": "Región de Los Lagos",
                    "Ciudad": "to Montt - Osorno",
                    "Institucion/Entidad": "Junta Nacional de Jardines Infantiles",
                    "Tipo Convocatoria": "EEPP",
                    "Origen": "JUNJI",
                    "Estado": "finalizadas",
                    "Tipo Postulacion": "Proceso de Selección",
                    "Cargo Profesional": "Técnico",
                    "Codigo Cargo Profesional": "cargo2",
                    "Codigo Area Interes": "area19",
                    "Codigo Region": "region10",
                    "Ganador": ""
                },
                "sort": [
                    0.03907092660665512,
                    707021
                ]
            },
            // More offers...
        ]
    }
}
```

## Pagination Logic


##  Scraping Risks


## Additional Findings (post-discovery analysis)

