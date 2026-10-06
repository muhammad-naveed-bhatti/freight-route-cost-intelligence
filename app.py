from __future__ import annotations

import json
import math
from datetime import date
from typing import Any

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Freight Route & Cost Intelligence", page_icon="🚚", layout="wide")

st.markdown("""
<style>
.block-container{padding-top:1.55rem;padding-bottom:2.5rem}
[data-testid="stMetric"]{border:1px solid #2a3447;border-radius:14px;padding:12px 14px;background:#151d2e}
.pill{border:1px solid #2a3447;border-radius:999px;padding:4px 9px;display:inline-block;margin:0 6px 6px 0;font-size:.78rem}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=86400)
def geocode(place: str) -> dict[str, Any] | None:
    try:
        r=requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q":place,"format":"jsonv2","limit":1},
            headers={"User-Agent":"FreightRouteCostIntelligence/1.0"},
            timeout=12,
        )
        r.raise_for_status()
        rows=r.json()
        if not rows: return None
        x=rows[0]
        return {"name":x.get("display_name",place),"lat":float(x["lat"]),"lon":float(x["lon"])}
    except Exception:
        return None

@st.cache_data(ttl=900)
def weather_at(lat: float, lon: float) -> dict[str, Any]:
    r=requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat,"longitude":lon,
            "current":"precipitation,snowfall,weather_code,wind_speed_10m,wind_gusts_10m",
            "forecast_days":1,"timezone":"auto",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600)
def fx_rate(target: str) -> float:
    if target=="USD": return 1.0
    fallback={"EUR":0.86,"GBP":0.75,"AED":3.6725,"QAR":3.64,"SAR":3.75,"PKR":278.0}
    try:
        r=requests.get("https://api.frankfurter.app/latest",params={"from":"USD","to":target},timeout=8)
        r.raise_for_status()
        return float(r.json()["rates"][target])
    except Exception:
        return fallback.get(target,1.0)

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius=6371.0088
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1)
    dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

def weather_risk(payload: dict[str,Any]) -> tuple[int,str]:
    c=payload.get("current",{}) or {}
    code=int(c.get("weather_code",0) or 0)
    gust=float(c.get("wind_gusts_10m",0) or 0)
    wind=float(c.get("wind_speed_10m",0) or 0)
    precip=float(c.get("precipitation",0) or 0)
    snow=float(c.get("snowfall",0) or 0)
    score=0
    reasons=[]
    if code in {95,96,99}: score+=40; reasons.append("thunderstorm")
    elif code in {65,67,75,82,86}: score+=30; reasons.append("severe precipitation")
    elif code in {45,48,61,63,66,71,73,80,81,85}: score+=18; reasons.append("visibility/precipitation")
    if gust>=70: score+=30; reasons.append("very strong gusts")
    elif gust>=50: score+=20; reasons.append("strong gusts")
    elif gust>=35: score+=10; reasons.append("moderate gusts")
    if wind>=45: score+=15; reasons.append("strong wind")
    elif wind>=30: score+=8; reasons.append("moderate wind")
    if precip>=7: score+=15; reasons.append("heavy precipitation")
    elif precip>=2: score+=8; reasons.append("precipitation")
    if snow>=2: score+=15; reasons.append("snow accumulation")
    elif snow>0: score+=8; reasons.append("snow")
    return min(score,100),", ".join(reasons or ["no major weather trigger"])

def risk_label(score:int)->str:
    return "High" if score>=60 else "Medium" if score>=30 else "Low"

def secret(key:str)->str:
    try: return str(st.secrets.get(key,""))
    except Exception: return ""

def road_distance(origin:dict[str,Any],destination:dict[str,Any])->float|None:
    key=secret("ORS_API_KEY")
    if not key: return None
    try:
        r=requests.post(
            "https://api.openrouteservice.org/v2/directions/driving-hgv",
            headers={"Authorization":key,"Content-Type":"application/json"},
            json={"coordinates":[[origin["lon"],origin["lat"]],[destination["lon"],destination["lat"]]]},
            timeout=20,
        )
        r.raise_for_status()
        return float(r.json()["features"][0]["properties"]["summary"]["distance"])/1000
    except Exception:
        return None

def default_rates(mode:str)->dict[str,float]:
    if mode=="Road": return {"distance":1.20,"weight":0.02,"volume":8.0,"handling":150.0}
    if mode=="Air": return {"distance":0.08,"weight":2.40,"volume":45.0,"handling":250.0}
    return {"distance":0.22,"weight":0.01,"volume":18.0,"handling":350.0}

def estimate(distance:float,weight:float,volume:float,rates:dict[str,float],weather:int,contingency:float)->dict[str,float]:
    d=distance*rates["distance"]
    w=weight*rates["weight"]
    v=volume*rates["volume"]
    h=rates["handling"]
    subtotal=d+w+v+h
    weather_pct=8 if weather>=60 else 4 if weather>=30 else 0
    wc=subtotal*weather_pct/100
    gc=subtotal*contingency/100
    return {
        "Distance":round(d,2),"Weight":round(w,2),"Volume":round(v,2),
        "Handling":round(h,2),"Weather contingency":round(wc,2),
        "General contingency":round(gc,2),"Total":round(subtotal+wc+gc,2),
    }

def run_apify(actor_id:str,token:str,urls:list[str],max_items:int)->pd.DataFrame:
    actor=actor_id.replace("/","~")
    r=requests.post(
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
        headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
        params={"clean":"true","format":"json","maxItems":max_items,"timeout":120},
        json={"startUrls":[{"url":u} for u in urls],"maxCrawlPages":max_items},
        timeout=135,
    )
    r.raise_for_status()
    data=r.json()
    return pd.json_normalize(data if isinstance(data,list) else data.get("items",[]))

st.title("🚚 Freight Route & Cost Intelligence")
st.caption("Route distance, weather risk, editable freight costing and quote collection in one planning dashboard.")
st.markdown(
    '<span class="pill">Nominatim</span><span class="pill">Open-Meteo</span>'
    '<span class="pill">Frankfurter FX</span><span class="pill">OpenRouteService-ready</span>'
    '<span class="pill">Apify-ready</span>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Route")
    origin_text=st.text_input("Origin","Lahore, Pakistan")
    destination_text=st.text_input("Destination","Dubai, UAE")
    mode=st.selectbox("Transport mode",["Road","Air","Sea"])
    st.divider()
    st.header("Cargo")
    weight=st.number_input("Weight (kg)",min_value=1.0,value=1000.0,step=50.0)
    volume=st.number_input("Volume (m³)",min_value=0.1,value=5.0,step=0.5)
    currency=st.selectbox("Output currency",["USD","EUR","GBP","AED","QAR","SAR","PKR"])
    st.divider()
    st.header("Planning rates")
    dflt=default_rates(mode)
    dr=st.number_input("Distance rate (USD/km)",min_value=0.0,value=float(dflt["distance"]),step=0.01)
    wr=st.number_input("Weight rate (USD/kg)",min_value=0.0,value=float(dflt["weight"]),step=0.01)
    vr=st.number_input("Volume rate (USD/m³)",min_value=0.0,value=float(dflt["volume"]),step=1.0)
    hr=st.number_input("Handling/base charges (USD)",min_value=0.0,value=float(dflt["handling"]),step=25.0)
    contingency=st.slider("General contingency (%)",0,25,5)
    st.caption("Editable planning assumptions — not carrier quotations.")

origin=geocode(origin_text)
destination=geocode(destination_text)
if not origin or not destination:
    st.error("Could not geocode one or both locations. Try city, country.")
    st.stop()

straight=haversine(origin["lat"],origin["lon"],destination["lat"],destination["lon"])
if mode=="Road":
    ors=road_distance(origin,destination)
    distance=ors if ors else straight*1.22
    distance_note="OpenRouteService road distance" if ors else "Great-circle × 1.22 planning estimate"
elif mode=="Sea":
    distance=straight*1.12
    distance_note="Great-circle × 1.12 sea planning estimate"
else:
    distance=straight
    distance_note="Great-circle distance"

with st.spinner("Checking live weather…"):
    try:
        ow=weather_at(origin["lat"],origin["lon"])
        dw=weather_at(destination["lat"],destination["lon"])
    except Exception as exc:
        st.error(f"Weather service unavailable: {exc}")
        st.stop()

orisk,oreason=weather_risk(ow)
drisk,dreason=weather_risk(dw)
route_risk=round((orisk+drisk)/2)
rates={"distance":dr,"weight":wr,"volume":vr,"handling":hr}
cost=estimate(distance,weight,volume,rates,route_risk,contingency)
converted=cost["Total"]*fx_rate(currency)

m1,m2,m3,m4=st.columns(4)
m1.metric("Planning distance",f"{distance:,.0f} km")
m2.metric("Weather risk",f"{risk_label(route_risk)} · {route_risk}/100")
m3.metric("Estimated cost",f"USD {cost['Total']:,.0f}")
m4.metric(f"Cost in {currency}",f"{converted:,.0f} {currency}")

t1,t2,t3,t4,t5=st.tabs(["Route intelligence","Cost breakdown","Scenario comparison","Apify quotes","About"])

with t1:
    st.subheader("Route overview")
    st.map(pd.DataFrame([{"lat":origin["lat"],"lon":origin["lon"]},{"lat":destination["lat"],"lon":destination["lon"]}]))
    st.dataframe(pd.DataFrame([
        {"point":"Origin","location":origin["name"],"risk":risk_label(orisk),"score":orisk,"reasons":oreason},
        {"point":"Destination","location":destination["name"],"risk":risk_label(drisk),"score":drisk,"reasons":dreason},
    ]),use_container_width=True,hide_index=True)
    st.caption(distance_note)

with t2:
    st.subheader("Planning cost breakdown")
    breakdown=pd.DataFrame([{"component":k,"usd":v} for k,v in cost.items()])
    st.dataframe(breakdown,use_container_width=True,hide_index=True,column_config={"usd":st.column_config.NumberColumn("USD",format="$%.2f")})
    st.bar_chart(breakdown.set_index("component")["usd"])
    st.warning("Planning estimate only; not a freight quotation.")

with t3:
    st.subheader("Mode scenario comparison")
    scenarios=[]
    for sm in ["Road","Air","Sea"]:
        dist=straight*(1.22 if sm=="Road" else 1.12 if sm=="Sea" else 1.0)
        est=estimate(dist,weight,volume,default_rates(sm),route_risk,contingency)
        scenarios.append({"mode":sm,"planning_distance_km":round(dist,1),"estimated_usd":est["Total"]})
    scenario_df=pd.DataFrame(scenarios).sort_values("estimated_usd")
    st.dataframe(scenario_df,use_container_width=True,hide_index=True,column_config={"estimated_usd":st.column_config.NumberColumn("Estimated USD",format="$%.2f")})
    st.download_button("Download scenario comparison (CSV)",scenario_df.to_csv(index=False).encode("utf-8-sig"),file_name=f"freight_route_scenarios_{date.today().isoformat()}.csv",mime="text/csv")

with t4:
    st.subheader("Optional freight quote collection with Apify")
    actor_id=st.text_input("Actor ID",value=secret("APIFY_ACTOR_ID"),placeholder="username/actor-name")
    token=st.text_input("Apify token",value=secret("APIFY_TOKEN"),type="password")
    urls_text=st.text_area("Freight / courier quote URLs, one per line",height=120)
    max_items=st.number_input("Maximum returned items",1,300,50)
    urls=[u.strip() for u in urls_text.splitlines() if u.strip()]
    with st.expander("Actor input preview"):
        st.code(json.dumps({"startUrls":[{"url":u} for u in urls],"maxCrawlPages":int(max_items)},indent=2),language="json")
    if st.button("Run quote collector",type="primary"):
        if not actor_id or not token:
            st.error("Actor ID and token are required.")
        elif not urls:
            st.error("Add at least one quote URL.")
        else:
            try:
                live=run_apify(actor_id,token,urls,int(max_items))
                st.success(f"Collected {len(live)} item(s).")
                st.dataframe(live,use_container_width=True,hide_index=True)
                if not live.empty:
                    st.download_button("Download raw quote results",live.to_csv(index=False).encode("utf-8-sig"),file_name=f"apify_freight_quotes_{date.today().isoformat()}.csv",mime="text/csv")
            except Exception as exc:
                st.error(f"Apify run failed: {exc}")

with t5:
    st.markdown("""
### Public-data design
- Nominatim / OpenStreetMap: geocoding.
- Open-Meteo: live endpoint weather.
- Frankfurter: currency conversion.
- OpenRouteService: optional road distance using ORS_API_KEY.
- Apify: optional carrier/freight quote collection.

### Cost model
Distance, weight, volume, handling, weather contingency and general contingency are transparent and editable. Default rates are demonstration assumptions only.
""")
    st.warning("Verify actual freight rates, duties, surcharges, insurance, customs costs and carrier service levels before shipment.")

st.divider()
st.caption("Portfolio demo by Muhammad Naveed · Logistics · Freight · Supply Chain")
