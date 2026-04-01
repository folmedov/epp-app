# Discovery: empleospublicos.cl API

## Endpoint Information

* The portal respond with 2 responses:
    * https://www.empleospublicos.cl/data/convocatorias2_nueva.txt?_=1774729833623
    * https://www.empleospublicos.cl/data/convocatorias_evaluacion_nueva.txt?_=1774729833754
* The first for jobs with status "Postulacion"
* The second for jobs with status "Evaluacion"

### Status: Postulacion
- **URL**: https://www.empleospublicos.cl/data/convocatorias2_nueva.txt?_=1774729833623
- **Method**: GET 

#### Payload Structure
* No payload, just a query param with a timestamp to avoid caching. This field is not required, as the endpoint works without it, but it is present in the requests made by the browser.
```text
_=1774729833623
```

#### Response Structure
* Response: array with 205 objects

```json
[
...
{
    "Ministerio": "Ministerio de Salud",
    "Institución / Entidad": "Servicio de Salud Aconcagua / Dirección Servicio Salud Aconcagua",
    "Cargo": "Administrativo en Admisión",
    "Nº de Vacantes": "1",
    "Área de Trabajo": "Administración",
    "Región": "Región de Valparaíso",
    "Ciudad": "San Esteban",
    "Tipo de Vacante": "Contrata",
    "Renta Bruta": "594027,00",
    "Fecha Inicio": "26/03/2026 0:00:00",
    "Fecha Cierre Convocatoria": "01/04/2026 23:59:00",
    "url": "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=139281&c=0&j=0&tipo=convpostularavisoTrabajo",
    "Tipo postulacion": "Postulacion en linea",
    "Cargo Profesional": "Administrativos",
    "esPrimerEmpleo": false,
    "TipoTxt": "Empleos P&uacute;blicos",
    "Priorizado": "False"
},
{
    "Ministerio": "Ministerio de Hacienda",
    "Institución / Entidad": "Comisión para el Mercado Financiero / Comisión para el Mercado Financiero",
    "Cargo": "Director(a) Dirección General Jurídica",
    "Nº de Vacantes": "0",
    "Área de Trabajo": "",
    "Región": "Región Metropolitana de Santiago",
    "Ciudad": "Santiago",
    "Tipo de Vacante": "",
    "Renta Bruta": "0,00",
    "Fecha Inicio": "24/03/2026 0:00:00",
    "Fecha Cierre Convocatoria": "07/04/2026 23:59:00",
    "url": "https://www.trabajando.cl/trabajo-empleo/comisi%C3%B3n%20para%20el%20mercado%20financiero/trabajo/6049069-director-a-direccion-general-juridica",
    "Tipo postulacion": "",
    "Cargo Profesional": "",
    "esPrimerEmpleo": false,
    "TipoTxt": "Comisi&oacute;n Mercado Financiero",
    "Priorizado": "False"
}
...
]
```

#### Pagination Logic
* No pagination


### Status: Evaluacion
- **URL**: https://www.empleospublicos.cl/data/convocatorias_evaluacion_nueva.txt?_=1774729833754
- **Method**: GET 

#### Payload Structure
* No payload, just a query param with a timestamp to avoid caching. This field is not required, as the endpoint works without it, but it is present in the requests made by the browser.
```text
_=1774730540565
```

#### Response Structure
* Response: array with 620 objects

```json
[
...
{
    "Ministerio": "Ministerio del Trabajo y Previsión Social",
    "Institución / Entidad": "Instituto de Seguridad Laboral /  ",
    "Cargo": "Analista Profesional Asesor(a) Riesgo Psicosocial, Acoso y Violencia en el Trabajo",
    "Nº de Vacantes": "1",
    "Área de Trabajo": "Area para cumplir misión institucional",
    "Región": "Región de La Araucanía",
    "Ciudad": "Temuco",
    "Tipo de Vacante": "Contrata",
    "Renta Bruta": "1863567,00",
    "Fecha Inicio": "09/03/2026 0:00:00",
    "Fecha Cierre Convocatoria": "07/04/2026 23:59:00",
    "url": "https://www.empleospublicos.cl/pub/convocatorias/convFicha.aspx?i=138525&c=0&j=0&tipo=avisotrabajoficha",
    "Tipo postulacion": "Postulacion en linea",
    "Cargo Profesional": "Profesionales",
    "esPrimerEmpleo": false,
    "TipoTxt": "Empleos P&uacute;blicos Evaluaci&oacute;n",
    "Priorizado": "False"
}
...
]
```

#### Pagination Logic
* No pagination

##  Scraping Risks
* The endpoint is public and does not require authentication, but it is not an official API, so it may change without notice. 
* The data is updated regularly, but there is no guarantee of stability, so we should implement error handling and monitoring to detect any changes in the structure or availability of the endpoint.
## Additional Findings (post-discovery analysis)

### EEPP as Aggregator
The portal does not only publish direct EEPP convocatorias. The `TipoTxt` field reveals the actual origin:

| TipoTxt (HTML-unescaped) | Count (postulacion) | Count (evaluacion) | source value |
|:---|:---|:---|:---|
| `Empleos Públicos` / `Empleos Públicos Evaluación` | 207 | 624 | `EEPP` |
| `JUNJI` | 16 | 0 | `JUNJI` |
| `Invitación a Postular` | 6 | 0 | `EXTERNAL` |
| `DIFUSION` | 3 | 0 | `DIFUSION` |
| `Comisión Mercado Financiero` | 1 | 0 | `CMF` |

All evaluacion records are direct EEPP. Non-EEPP records only appear in postulacion.

### URL Instability Across States
The URL for the same offer changes depending on its state:
- **postulacion**: `convpostularavisoTrabajo.aspx?i=<id>`
- **evaluacion**: `convFicha.aspx?i=<id>`

The `?i=` query parameter is the stable identifier. The URL itself is not a reliable identity key.

### External ID Extraction per Domain

| Domain | URL pattern | Extraction rule |
|:---|:---|:---|
| `empleospublicos.cl` | `?i=139281` | `i` query param |
| `junji.myfront.cl` | `/oferta-de-empleo/19560/slug` | segment at index 2 of path |
| `*.trabajando.cl` | `/trabajo/6049750-slug` | numeric prefix before first `-` |
| `educacionpublica.gob.cl`, `renca.cl`, etc. | no stable ID | `None` |