Search the news from the last 3 days for snowfall and road conditions on the Shimla–Kinnaur–Spiti route in Himachal Pradesh, India: Lahaul-Spiti, Kinnaur, NH-5, NH-505, Reckong Peo to Kaza, Nako, Malling, Tabo, Kaza. Also look for the latest IMD Shimla forecast for snow or dry weather.

Reply with ONE JSON object and nothing else:
{"schema":"spiti-notes/1","written_at":"<now, UTC, ISO 8601>",
 "items":[{"kind":"observed","date":"YYYY-MM-DD","date_to":"YYYY-MM-DD","area":"","places":[],"summary":"","source":"","url":"","published":"YYYY-MM-DD"}]}

Rules:
- kind: observed (snow actually fell; date is when it fell), forecast (official IMD snow forecast; dates it covers), dry_forecast (official dry spell), road (closure, reopening or slippery-road advisory), outlook (monthly or seasonal outlook).
- Only dated, specific items from a named news outlet, IMD, the police or the district administration. Skip anything about an earlier year and anything vague.
- "summary" is one sentence in your own words, at most 240 characters. Do not copy sentences from the article.
- "places" uses these ids when the item names the place, otherwise leave it empty: shimla, narkanda, kalpa, nako, tabo, kaza, komic, sarahan.
- If you find nothing new, return "items": [].
