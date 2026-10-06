# Freight Route & Cost Intelligence

A Streamlit logistics-planning app for route distance, weather risk, editable freight-cost estimation and quote collection.

## Features

- Origin / destination geocoding
- Route-distance planning
- Live endpoint weather risk
- Editable freight-cost model
- Weight, volume, handling and contingency inputs
- Currency conversion
- Road / Air / Sea scenario comparison
- CSV export
- Optional Apify freight-quote collection
- Optional OpenRouteService road routing

## Public APIs

The app uses:
- **Nominatim / OpenStreetMap** for geocoding
- **Open-Meteo** for live weather
- **Frankfurter** for currency conversion
- **OpenRouteService** optionally for road routing with an API key

## Optional secrets

```toml
APIFY_TOKEN = "your-token"
APIFY_ACTOR_ID = "username/actor-name"
ORS_API_KEY = "your-openrouteservice-key"
```

Never commit secrets.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Deploy `app.py` from the repository root on Streamlit Community Cloud.

## Important

The internal cost calculation is a planning model, not a carrier quote. Default rates are demonstration assumptions and should be replaced with actual commercial rates for real-world use.
