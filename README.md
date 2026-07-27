# weather-brief

A morning weather text that answers two questions and stops: what should I wear,
and do I need an umbrella. Celsius. No API key, no dependencies, one file.

```
👕🧥 Cool, 12-17°C
☂️ Umbrella. Rain 8am to 10am and 5pm to 7pm (8mm).
Windy, gusting to 38 km/h. Something windproof.
Portland 97205 · Mon 27 Jul · overcast · feels 8-15°C
```

Most days it is two lines, because most days there is nothing to warn you about:

```
👕 Warm, 16-21°C
Portland 97205 · Sun 26 Jul · overcast · feels 15-23°C
```

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

## Daily at 7am

The included GitHub Actions workflow runs it for you, whether or not your laptop
is open. Push this repo to GitHub, then add four repository secrets under
**Settings → Secrets and variables → Actions**:

| Secret | Value |
| --- | --- |
| `NTFY_TOPIC` | the topic from `set-topic` |
| `WEATHER_LAT` | latitude from `weather.py where` |
| `WEATHER_LON` | longitude from `weather.py where` |
| `WEATHER_LABEL` | display name, e.g. `Portland 97205` |

Environment variables override the config file, so the workflow needs nothing
checked in. Trigger it by hand once from the Actions tab to confirm it works.

Two things to know about GitHub's scheduler: it runs in UTC, and it can fire ten
or twenty minutes late when the platform is busy. The workflow handles the first
by waking on five different UTC hours and passing `--at-hour 7`, which makes the
script exit without sending unless the local hour at your coordinates really is
7. Daylight saving takes care of itself. The lateness you cannot fix; expect the
message somewhere in the 7am hour rather than at 7:00 sharp.

If you would rather have it exact and do not mind that it only fires when the Mac
is awake, use launchd instead and drop the `--at-hour` flag.

## Commands

| | |
| --- | --- |
| `weather.py` | today's brief |
| `weather.py today --detail` | plus an hourly temperature and rain table |
| `weather.py today --full-day` | count rain from midnight rather than from now |
| `weather.py send` | brief, and push it to your phone |
| `weather.py send --dry-run` | everything except the push |
| `weather.py set-location 97205` | US postal code |
| `weather.py set-location SW1A --country gb` | elsewhere |
| `weather.py set-location --coords=51.5,-0.13` | skip geocoding |
| `weather.py where` | show what is saved and where |

Config lives at `~/.config/weather-brief/config.json`.

## How the advice is decided

Everything keys off **apparent** temperature, not the raw number, and only the
07:00 to 21:00 window, because the 3am low is not what you are dressing for. The
range shown is real temperature; the wardrobe is picked off feels-like.

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
happened overnight is not a reason to carry anything. When the line does appear it
names the wet stretches: one or two get spelled out, three or more collapse to "on
and off from X to Y". Snow is handled separately and always gets mentioned.

Both numbers are config, not code. Raise them in
`~/.config/weather-brief/config.json`:

```json
{ "umbrella_mm": 8, "umbrella_peak_mm": 2.5 }
```

Everything else only appears when it crosses a line: wind over 35 km/h, UV index
7 or higher on a day that is not already wet, feels-like above 38° or below -10°,
and a daytime swing of 9° or more.

## Why these services

**[Open-Meteo](https://open-meteo.com)** for the forecast. Free for
non-commercial use, no key to lose, no account to expire, and it aggregates
national weather-service models rather than reselling one vendor's feed.

**[Zippopotam](https://zippopotam.us)** for postal codes, hit exactly once per
`set-location` and then cached. If it ever disappears, `--coords` is the escape
hatch and nothing else changes.

**[ntfy](https://ntfy.sh)** for delivery. Publishing is one HTTP POST with no
auth, which is the whole reason to prefer it over email or SMS: there is no
sender reputation, no domain verification, and no carrier registration to fall
out from under you.
