// Query corpora matching the three code paths in AddressRepository.SearchAsync:
//
//  ZIP_QUERIES     contain a valid 5-digit Illinois ZIP -> indexed zip_code
//                  filter + similarity ranking over a few thousand rows.
//  KNN_QUERIES     contain no ZIP -> GiST trigram KNN over the whole
//                  il_addresses table (the expensive path).
//  BAD_ZIP_QUERIES contain a 5-digit number that matches no zip_code row ->
//                  worst case: the ZIP query runs, returns nothing, and the
//                  code falls through to the full KNN query (two round trips).

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

export const KNN_QUERIES: string[] = [
  '1916 lombard avenue berwyn illinois',
  '233 south wacker drive chicago',
  'one hundred north western avenue chicago',
  '500 east monroe street springfield',
  '1401 west green street urbana',
  '4800 north broadway chicago',
  '201 west lake street addison',
  'algonquin road schaumburg',
  '300 south riverside plaza',
  'cannon drive lincoln park chicago',
];

export const BAD_ZIP_QUERIES: string[] = [
  '742 evergreen terrace springfield il 00001',
  '1060 w addison st chicago il 99999',
  '350 fifth avenue chicago il 00123',
  '1600 main street peoria il 99998',
  '12 oak lane naperville il 00002',
];

export const ALL_VERIFY_QUERIES = [...ZIP_QUERIES, ...KNN_QUERIES, ...BAD_ZIP_QUERIES];

export function pick<T>(arr: T[], i: number): T {
  return arr[i % arr.length];
}
