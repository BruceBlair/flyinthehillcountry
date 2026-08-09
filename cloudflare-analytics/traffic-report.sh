#!/usr/bin/env bash
# Prints a 7-day traffic summary (requests, pageviews, uniques, top country)
# for every zone in the Cloudflare account, straight from the GraphQL
# Analytics API. Works with zero extra accounts or per-page tracking code —
# useful for the 26 domains that only serve redirects and can never run JS.
#
# Requires CF_API_TOKEN with Account Analytics:Read + Zone:Read scope.
#   export CF_API_TOKEN=xxxxx
#   ./traffic-report.sh

set -euo pipefail

CF_API_TOKEN="${CF_API_TOKEN:?Set CF_API_TOKEN first}"
API="https://api.cloudflare.com/client/v4"
SINCE=$(date -u -d '7 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-7d +%Y-%m-%d)

zones=$(curl -s -H "Authorization: Bearer $CF_API_TOKEN" "$API/zones?per_page=50" \
  | jq -r '.result[] | "\(.id)\t\(.name)"')

printf "%-32s %10s %10s %10s  %s\n" "DOMAIN" "REQUESTS" "PAGEVIEWS" "UNIQUES" "TOP COUNTRY"

while IFS=$'\t' read -r zone_id zone_name; do
  query='query($zoneTag: String!, $since: Date!) {
    viewer {
      zones(filter: {zoneTag: $zoneTag}) {
        httpRequests1dGroups(limit: 7, filter: {date_geq: $since}, orderBy: [date_DESC]) {
          sum { requests pageViews countryMap { clientCountryName requests } }
          uniq { uniques }
        }
      }
    }
  }'
  payload=$(jq -n --arg q "$query" --arg zt "$zone_id" --arg since "$SINCE" \
    '{query: $q, variables: {zoneTag: $zt, since: $since}}')

  resp=$(curl -s -X POST "$API/graphql" \
    -H "Authorization: Bearer $CF_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$payload")

  reqs=$(echo "$resp" | jq '[.result.viewer.zones[0].httpRequests1dGroups[].sum.requests] | add // 0')
  views=$(echo "$resp" | jq '[.result.viewer.zones[0].httpRequests1dGroups[].sum.pageViews] | add // 0')
  uniq=$(echo "$resp" | jq '[.result.viewer.zones[0].httpRequests1dGroups[].uniq.uniques] | add // 0')
  top_country=$(echo "$resp" | jq -r '
    [.result.viewer.zones[0].httpRequests1dGroups[].sum.countryMap[]]
    | group_by(.clientCountryName)
    | map({country: .[0].clientCountryName, requests: (map(.requests) | add)})
    | sort_by(-.requests) | .[0].country // "-"')

  printf "%-32s %10s %10s %10s  %s\n" "$zone_name" "$reqs" "$views" "$uniq" "$top_country"
done <<< "$zones"
