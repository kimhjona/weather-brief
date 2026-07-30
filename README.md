# weather-brief

A morning weather notification that answers two questions and stops: what should I wear,
and do I need an umbrella. Celsius. No API key, no dependencies, one file.

```
12-17° · AQI 34
👕🧥 · ☂️ 8-10am, 5-7pm, 8mm · 💨 38km/h
Warmest 1-4pm
Portland · Mon 27 Jul
```

Four lines, always, in the same order. Most days the second one is nearly
empty, because most days there is nothing to warn you about:

```
16-21° · AQI 41
👕 · no rain
Warmest 2-6pm
Portland · Sun 26 Jul
```

The shape is fixed on purpose. A phone truncates a notification title at
roughly twenty characters and wraps the body around twenty-four, so the title
is numbers only: the temperature range you dress for and the air you breathe,
left to right, nothing in front of them. No emoji tag, no adjective, no unit
that a number does not need. Line two is every other figure worth having, and
only when it crosses a threshold. Line three says when the heat lands. Line
four is where and when, short enough to survive the wrap in one piece.

There is no line for the sky. "Overcast" is the one thing here you can settle
by looking out of the window, and at the width of a phone it cost more than it
told you.

## Setup

```sh
python3 weather.py set-location 97205     # resolves once, caches the coordinates
python3 weather.py                        # print today's brief
```

To get it on your phone, install [ntfy](https://apps.apple.com/app/ntfy/id1625396347)
from the App Store, then:

```sh
python3 weather.py set-topic              # generates a random private topic
```

Subscribe to the topic it prints, then `python3 weather.py send` to test.

Anyone who knows a topic name can read it, which is why the generated one is
random. It is not a secret worth protecting, but do not rename it to `weather`.

## Daily at 6:45am

The included GitHub Actions workflow runs it for you, whether or not your laptop
is open. Push this repo to GitHub, then add four repository secrets under
**Settings → Secrets and variables → Actions**:

| Secret | Value |
| --- | --- |
| `NTFY_TOPIC` | the topic from `set-topic` |
| `WEATHER_LAT` | latitude from `weather.py where` |
| `WEATHER_LON` | longitude from `weather.py where` |
| `WEATHER_LABEL` | display name, e.g. `Portland` |

Environment variables override the config file, so the workflow needs nothing
checked in. Trigger it by hand once from the Actions tab to confirm it works.

GitHub's scheduler runs in UTC and dispatches late, sometimes by two hours. So
the workflow does not try to run at 6:45. It runs once in the small hours and
passes `--deliver-at 06:45`, which publishes the brief immediately with a release
time attached; ntfy holds the message and hands it to your phone at 6:45 local.
The cron owes us one run at some point in the several hours beforehand, and
nothing worse than a late dispatch can happen. Daylight saving takes care of
itself, because the script reads the UTC offset off the forecast rather than
trusting the cron.

The brief is written for 6:45 regardless of when the job ran, so a 3am run still
counts rain from breakfast onward and not from overnight.

One cron is one point of failure: if GitHub drops that dispatch entirely, you get
nothing that morning. Scheduling on an odd minute rather than the top of the hour
makes that much less likely. A second cron would not help, because ntfy does not
let an anonymous topic see its own queued-but-undelivered messages, so the
backup run cannot tell the brief is already waiting and would just send a second
one.

If a delivery time already went by when the job runs, the brief goes out
immediately instead. That is what a manual run from the Actions tab does at noon.

## Commands

| | |
| --- | --- |
| `weather.py` | today's brief |
| `weather.py today --detail` | plus an hourly temperature and rain table |
| `weather.py today --full-day` | count rain from midnight rather than from now |
| `weather.py send` | brief, and push it to your phone |
| `weather.py send --dry-run` | everything except the push |
| `weather.py send --deliver-at 06:45` | publish now, ntfy delivers at 6:45 local |
| `weather.py set-location 97205` | US postal code |
| `weather.py set-location SW1A --country gb` | elsewhere |
| `weather.py set-location --coords=51.5,-0.13` | skip geocoding |
| `weather.py where` | show what is saved and where |

Config lives at `~/.config/weather-brief/config.json`.

## How the advice is decided

Everything keys off **apparent** temperature, not the raw number, and only the
07:00 to 21:00 window, because the 3am low is not what you are dressing for. The
one range shown is real temperature, since that is the number you would quote to
someone; the wardrobe below it is picked off feels-like. Only the icons are
shown, never the word, which the range already tells you.

| Feels-like high | | |
| --- | --- | --- |
| 26°+ | 🩳👕 | Hot |
| 18°+ | 👕 | Warm |
| 14°+ | 👕🧥 | Cool |
| 10°+ | 🧥 | Chilly |
| 5°+ | 🧥🧣 | Cold |
| 0°+ | 🧥🧣🧤 | Very cold |
| below 0° | 🧥🧣🧤🥾 | Freezing |

**Umbrella.** Most rain does not deserve a notification. Walking through light
drizzle is fine, so the brief says nothing at all unless one of two things is
true: **5mm** of rain is still to come across the day, or **1.5mm** falls in a
single hour. The first catches the day that soaks you slowly, the second the
burst that soaks you at once. Seattle drizzle at 0.2mm/hr clears neither bar and
stays silent, which is the point.

Only rain from the current hour onward counts, because a downpour that already
happened overnight is not a reason to carry anything. Below both bars the cell
reads `no rain`; above them it names the wet stretches and the total, as in
`☂️ 8-10am, 5-7pm, 8mm`. One or two stretches get spelled out, three or more
collapse to a single span from the first drop to the last, which is wrong in
the middle and right about when to carry the umbrella. Snow is handled
separately and always gets mentioned.

Both numbers are config, not code. Raise them in
`~/.config/weather-brief/config.json`:

```json
{ "umbrella_mm": 8, "umbrella_peak_mm": 2.5 }
```

**Warmest.** A range tells you how hot, not when, and on a day that swings
twelve degrees the hour is the thing you are actually planning around. The line
names a span rather than a peak, because a high of 23.5° at 5pm is usually
within a degree of itself from 3pm to 8pm and calling it "5pm" would claim a
sharpness the day does not have. The band that counts as near the high scales
with the swing, so a flat day names a narrow window instead of the whole
afternoon.

Everything else only appears when it crosses a line: wind over 35 km/h, and UV
index 6 or higher on a day that is not already wet.

None of it comes with a sentence attached. The brief used to explain itself
("Big swing. Wear layers.", "UV index 7. Sunscreen.") and the explanations were
the first thing a small screen cut, taking the numbers with them. A range of
12-24° is its own argument for layers.

**Air quality** rides in the title, the worst US AQI of the 07:00 to 21:00
window. It is the one number that is always shown rather than shown on
threshold, because a number you see every morning is a number you can read at a
glance. At 101 and above it picks up a 😷, which is where the EPA's advice
changes:

| AQI | |
| --- | --- |
| 101+ | unhealthy for sensitive groups, go easy outside if your lungs are touchy |
| 151+ | unhealthy, skip the outdoor workout |
| 201+ | very unhealthy, stay inside, windows shut |
| 301+ | hazardous, stay inside |

The scale is US AQI everywhere, including outside the US, on the grounds that one
familiar scale beats two correct ones. Air quality comes from a different host
than the forecast, so it fails on its own: if it is down, the title falls back to
`12-17°C` and the rest of the brief arrives as usual.

## Why these services

**[Open-Meteo](https://open-meteo.com)** for the forecast, and its air quality
endpoint for the AQI. Free for non-commercial use, no key to lose, no account to
expire, and it aggregates national weather-service models rather than reselling
one vendor's feed.

**[Zippopotam](https://zippopotam.us)** for postal codes, hit exactly once per
`set-location` and then cached. If it ever disappears, `--coords` is the escape
hatch and nothing else changes.

**[ntfy](https://ntfy.sh)** for delivery. Publishing is one HTTP POST with no
auth, which is the whole reason to prefer it over email or SMS: there is no
sender reputation, no domain verification, and no carrier registration to fall
out from under you.
