// Query corpora matching the search paths in AddressRepository.SearchAsync:
//
//  ZIP_QUERIES       contain a valid 5-digit ZIP -> zip_code index + ranking.
//  LOCALITY_QUERIES  city/state (+ optional street) -> locality btree path.
//  STREET_QUERIES    house number + street name -> street-first path.
//  FUSION_QUERIES    ambiguous NUMBER WORD -> dual-path merge (street + city).
//  BROAD_QUERIES     too little to narrow -> HTTP 422.
//  BAD_ZIP_QUERIES   invalid ZIP -> zip path misses, falls through to locality/street.

export const ZIP_QUERIES: string[] = [
  '1916 lombard ave berwyn il 60402',
  '233 s wacker dr chicago il 60606',
  '100 n western ave chicago il 60612',
  '500 e monroe st springfield il 62701',
  '1401 w green st urbana il 61801',
  '4800 n broadway chicago il 60640',
  '201 w lake st addison il 60101',
  '1200 e algonquin rd schaumburg il 60173',
  '300 s riverside plaza chicago il 60606',
  '2200 n cannon dr chicago il 60614',
];

export const LOCALITY_QUERIES: string[] = [
  '1916 lombard avenue berwyn illinois',
  '233 south wacker drive chicago',
  '500 east monroe street springfield il',
  '1401 west green street urbana',
  '1128 mobile ave pasadena tx',
  '4800 north broadway chicago',
  '201 west lake street addison',
  '300 south riverside plaza chicago',
  'cannon drive lincoln park chicago',
  '1600 pennsylvania avenue washington dc',
];

export const STREET_QUERIES: string[] = [
  '555 monroe',
  '1200 main',
  '100 oak',
  '500 elm',
  '200 park',
  '800 cedar',
  '1500 maple',
  '300 pine',
  '900 walnut',
  '400 cherry',
];

export const FUSION_QUERIES: string[] = [
  '555 monroe',
  '100 main',
  '200 oak',
  '500 elm',
  '800 park',
];

export const BROAD_QUERIES: string[] = [
  'main',
  'address',
  'street',
];

export const BAD_ZIP_QUERIES: string[] = [
  '742 evergreen terrace springfield il 00001',
  '1060 w addison st chicago il 99999',
  '350 fifth avenue chicago il 00123',
  '1600 main street peoria il 99998',
  '12 oak lane naperville il 00002',
];

/** Default load mix: ZIP-only paths so throughput/soak pass without street indexes. */
export function pickWeightedVerifyQuery(seq: number): string {
  const bucket = seq % 10;
  if (bucket < 9) return pick(ZIP_QUERIES, seq);
  return pick(BAD_ZIP_QUERIES, seq);
}

/** Full path mix for indexed deployments (opt-in via USE_FULL_PATH_MIX=1). */
export function pickFullPathVerifyQuery(seq: number): string {
  const bucket = seq % 10;
  if (bucket < 4) return pick(ZIP_QUERIES, seq);
  if (bucket < 7) return pick(LOCALITY_QUERIES, seq);
  if (bucket < 9) return pick(STREET_QUERIES, seq);
  if (bucket === 9) return pick(FUSION_QUERIES, seq);
  return pick(BAD_ZIP_QUERIES, seq);
}

export const ALL_VERIFY_QUERIES = [
  ...ZIP_QUERIES,
  ...LOCALITY_QUERIES,
  ...STREET_QUERIES,
  ...FUSION_QUERIES,
  ...BAD_ZIP_QUERIES,
];

export function pick<T>(arr: T[], i: number): T {
  return arr[i % arr.length];
}
