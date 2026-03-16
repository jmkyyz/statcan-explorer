# StatCan Data Explorer — Setup Guide

This is a two-part application:

| Part | File | What it does |
|------|------|-------------|
| **Proxy** | `proxy.py` | Python server that calls the Statistics Canada WDS API and returns clean JSON. Handles CORS so your browser can fetch the data. |
| **Frontend** | `statcan-explorer.html` | Single-file web app. Open in any browser. Talks to the proxy on `localhost:5000`. |

---

## 1 · Prerequisites

- **Python 3.9+**
- **pip**
- An internet connection (proxy calls statcan.gc.ca)

---

## 2 · Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `flask` — lightweight web framework for the proxy
- `flask-cors` — adds CORS headers so the browser can call the proxy
- `requests` — makes HTTP calls to the StatCan WDS API

---

## 3 · Start the proxy

```bash
python proxy.py
```

You should see:
```
============================================================
  StatCan WDS Proxy
  Listening on http://localhost:5000
============================================================
```

Leave this terminal open while you use the app.

---

## 4 · Open the frontend

Open `statcan-explorer.html` in your browser. No server needed — it's a static file.

> **Tip:** In Chrome/Firefox you can just double-click the file, or drag it into the browser.

---

## 5 · Use the app

1. **Select a topic** (GDP, CPI, LFS, Housing, SEPH)
2. **Choose up to 4 series** from the list
3. **Set your date range** (From / To year)
4. **Pick output frequency** — Original, Quarterly, or Annual
5. **Choose a transform** — Level, Period % Change, YoY % Change, or Index
6. Click **↓ Fetch Data** — the proxy calls Statistics Canada and returns real data
7. Switch between **Line / Bar / Area** charts with the toolbar tabs
8. Click **↓ Export XLSX** to download the data as a spreadsheet

---

## Proxy API reference

The proxy exposes three endpoints:

### `GET /api/series`
Fetch time-series data for one or more vectors.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vectors` | string | required | Comma-separated vector IDs, e.g. `41690973,2062809` |
| `from` | int | — | Start year filter, e.g. `2010` |
| `to` | int | — | End year filter, e.g. `2024` |
| `periods` | int | `360` | Max periods to request from StatCan (capped at 1200) |

**Example:**
```
GET http://localhost:5000/api/series?vectors=41690973&from=2015&to=2024
```

**Response:**
```json
{
  "series": [
    {
      "vectorId": 41690973,
      "frequency": "Monthly",
      "frequencyCode": 6,
      "scalarFactorCode": 0,
      "multiplier": 1,
      "data": [
        { "label": "2015-01", "date": "2015-01-01", "value": 125.7 },
        ...
      ]
    }
  ]
}
```

---

### `GET /api/metadata`
Get series info (title, frequency, scalar) for one or more vectors.

| Parameter | Type | Description |
|-----------|------|-------------|
| `vectors` | string | Comma-separated vector IDs |

**Example:**
```
GET http://localhost:5000/api/metadata?vectors=41690973,2062809
```

---

### `GET /api/table-metadata`
Get full table/cube metadata (dimensions, members, date range).

| Parameter | Type | Description |
|-----------|------|-------------|
| `pid` | string | Product ID, e.g. `18100004` or `18-10-0004-01` |

**Example:**
```
GET http://localhost:5000/api/table-metadata?pid=18-10-0004-01
```

---

### `GET /api/health`
Returns `{"status": "ok"}`. Useful to confirm the proxy is running.

---

## Finding vector IDs

Each StatCan series has a unique **Vector ID** (a `V` number). The series pre-loaded in the app use these vectors:

| Series | Vector ID | Table |
|--------|-----------|-------|
| Real GDP (Chained 2012 $M) | V62305752 | 36-10-0104-01 |
| Nominal GDP | V62305593 | 36-10-0104-01 |
| Household Final Consumption | V62305594 | 36-10-0104-01 |
| Gross Fixed Capital Formation | V62305601 | 36-10-0104-01 |
| All-items CPI | V41690973 | 18-10-0004-01 |
| CPI Food | V41690975 | 18-10-0004-01 |
| CPI Shelter | V41690980 | 18-10-0004-01 |
| CPI Energy | V41691048 | 18-10-0004-01 |
| LFS Employment (000s) | V2062809 | 14-10-0287-01 |
| LFS Unemployment Rate | V2062815 | 14-10-0287-01 |
| LFS Participation Rate | V2062817 | 14-10-0287-01 |
| LFS Avg Hours | V2062840 | 14-10-0287-01 |
| Housing Starts – Total | V56857 | 34-10-0135-01 |
| Housing Starts – Urban | V56858 | 34-10-0135-01 |
| Housing Starts – Single | V56860 | 34-10-0135-01 |
| Housing Starts – Multi | V56861 | 34-10-0135-01 |
| SEPH Payroll Employees | V1597509 | 14-10-0190-01 |
| SEPH Avg Weekly Earnings (incl. OT) | V1597510 | 14-10-0190-01 |
| SEPH Avg Weekly Earnings (excl. OT) | V1597511 | 14-10-0190-01 |
| SEPH Avg Hours | V1597512 | 14-10-0190-01 |

To find the V-number for any other StatCan series:
1. Go to the table on [www150.statcan.gc.ca](https://www150.statcan.gc.ca)
2. Hover over a data cell — the tooltip shows the V-number
3. Or call `/api/table-metadata?pid=<tableId>` to see all dimensions and members

---

## Production deployment

To host the proxy on a server instead of localhost:

1. Set the environment variable `PORT` to your desired port, or edit `proxy.py`
2. Use a production WSGI server: `gunicorn proxy:app`
3. Update `PROXY_URL` at the top of `statcan-explorer.html` to match your server URL
4. Consider restricting CORS in `proxy.py` to only your frontend's origin

---

## StatCan API limits

- **Rate limit:** 50 requests/second globally; 25/second per IP
- **Availability:** Data updates daily at 8:30 AM EST; some tables unavailable 12 AM – 8:30 AM EST
- **No API key required** — the WDS is a public, unauthenticated API

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Error: fetch failed" | Make sure `python proxy.py` is running |
| "HTTP 502" | StatCan API is down or slow — try again |
| "HTTP 504" | Request timed out — try a shorter date range |
| Data looks wrong | Check the vector ID in `statcan-explorer.html` against the StatCan website |
| No data for a series | The vector may be terminated or the date range may pre-date availability |
