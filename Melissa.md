# Melissa — Address Data Sources

> Transcribed from the two screenshots embedded in `Melissa.docx`. The original
> document contained no selectable text, only images, so the tables and notes
> below were transcribed from those screenshots.

## Active Government Sources

| Source | URL | License |
|---|---|---|
| National Address Database (NAD) | https://nationaladdressdata.s3.amazonaws.com/NAD_r15_TXT.zip | US Public Domain |
| TIGER/Line ADDRFEAT (Census Bureau) | https://www2.census.gov/geo/tiger/TIGER2023/ADDRFEAT/tl_2023_<FIPS>_addrfeat.zip (per county FIPS) | US Public Domain |

The other two active sources — OpenAddresses and OpenStreetMap — are community/open-data, not government.

## Identified-but-not-yet-integrated Government Sources

ArcGIS / state open-data portals:

- **Cook County IL** — https://hub-cookcountyil.opendata.arcgis.com
- **IndianaMap Statewide** — https://indianamap.org
- **Lake County IL** — https://data-lakecountyil.opendata.arcgis.com
- **DuPage County IL** — https://gisdata-dupage.opendata.arcgis.com
- **St. Louis County MO** — https://data-stlcogis.opendata.arcgis.com
- **City of Champaign IL** — https://gis-cityofchampaign.opendata.arcgis.com
- **WI Statewide (SCO)** — https://sco.wisc.edu/data/address-points
- **MSDIS Missouri** — https://data-msdis.opendata.arcgis.com
- **KyGovMaps Kentucky** — https://opengisdata.ky.gov

## All Sources In Use

| Source | URL | License |
|---|---|---|
| OpenAddresses (OA) | No single URL — fetched via Batch API; per-source config lives in `.data/midwest_sources.json` | OpenAddresses License |
| National Address Database (NAD) | https://nationaladdressdata.s3.amazonaws.com/NAD_r15_TXT.zip | US Public Domain |
| OpenStreetMap (OSM) | Geofabrik PBF mirrors, e.g. https://download.geofabrik.de/north-america/us/illinois-latest.osm.pbf (one per state) | ODbL |
| TIGER/Line ADDRFEAT | https://www2.census.gov/geo/tiger/TIGER2023/ADDRFEAT/tl_2023_<FIPS>_addrfeat.zip (per county FIPS) | US Public Domain |

**Notes:** _(The "Notes" section was cut off at the bottom of the original screenshot and is not recoverable from the document.)_
