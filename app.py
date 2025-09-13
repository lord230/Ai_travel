# streamlit_ai_tour_guide.py
# Streamlit AI Tour Guide — Corrected Scoring Logic

import streamlit as st
import pandas as pd
import math
import json
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional

# Import POI data from the separate file
from Pois import POIS_BY_STATE, placeholder_image_url

# ------------------------------
# PAGE CONFIG & THEME
# ------------------------------
st.set_page_config(page_title="AI Tour Guide", layout="wide")

# Initialize session state variables
if "theme" not in st.session_state:
    st.session_state.theme = "light"
if "itinerary" not in st.session_state:
    st.session_state.itinerary = None
if "selected_day" not in st.session_state:
    st.session_state.selected_day = 1
if "last_params" not in st.session_state: # To track changes and trigger regeneration
    st.session_state.last_params = {}

# CSS for theming with .tag-pill style
LIGHT_CSS = """
<style>
    :root{--bg: #ffffff; --card: #f7fbff; --text: #0b2545; --muted: #4b5563; --accent: #0b69ff;}
    body { background: var(--bg); color: var(--text); }
    .card { background: var(--card); border-radius:12px; padding:12px; box-shadow: 0 6px 18px rgba(11,38,69,0.06); margin-bottom:10px; }
    .meta { color: var(--muted); font-size:13px; }
    .small { color: var(--muted); font-size:13px; }
    .tag-pill { display: inline-block; padding: 4px 8px; font-size: 11px; font-weight: 600; background-color: #e0e7ff; color: #4338ca; border-radius: 12px; margin-right: 5px; margin-top: 5px; }
</style>
"""
DARK_CSS = """
<style>
    :root{--bg: #0b1220; --card: #071127; --text: #dbeafe; --muted: #94a3b8; --accent: #3b82f6;}
    body { background: var(--bg); color: var(--text); }
    .card { background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)); border-radius:12px; padding:12px; box-shadow: 0 6px 18px rgba(2,6,23,0.6); margin-bottom:10px; }
    .meta { color: var(--muted); font-size:13px; }
    .small { color: var(--muted); font-size:13px; }
    .tag-pill { display: inline-block; padding: 4px 8px; font-size: 11px; font-weight: 600; background-color: #312e81; color: #e0e7ff; border-radius: 12px; margin-right: 5px; margin-top: 5px; }
</style>
"""
st.markdown(DARK_CSS if st.session_state.theme == "dark" else LIGHT_CSS, unsafe_allow_html=True)


# ------------------------------
# CORE LOGIC: ITINERARY GENERATION & HELPERS
# ------------------------------
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.asin(math.sqrt(a))

def travel_time_hours(p1: Dict[str, Any], p2: Dict[str, Any], avg_speed_kmph: int = 30) -> float:
    distance = haversine(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
    return max(0.25, distance / avg_speed_kmph)

def score_poi(poi: Dict[str, Any], travel_style: str) -> int:
    score = 10 if travel_style in poi.get("tags", []) else 0
    score += max(0, 5 - poi.get("duration", 1) * 2)
    return score

def recompute_day_times(day_activities: List[Dict], start_time_str: str) -> List[Dict]:
    new_list = []
    time_cursor = datetime.strptime(start_time_str, "%H:%M")
    prev_poi = None
    for poi in day_activities:
        if prev_poi:
            travel_h = travel_time_hours(prev_poi, poi)
            time_cursor += timedelta(hours=travel_h)
        start_time = time_cursor
        end_time = start_time + timedelta(hours=poi.get("duration", 1))
        poi_copy = poi.copy()
        poi_copy["start_time"] = start_time.strftime("%H:%M")
        poi_copy["end_time"] = end_time.strftime("%H:%M")
        new_list.append(poi_copy)
        time_cursor = end_time + timedelta(minutes=30)
        prev_poi = poi_copy
    return new_list

def generate_itinerary(
    city_pois: List[Dict], days: int, travel_style: str, start_time_str: str,
    stay_coord: Optional[Tuple[float, float]], day_hours_budget: float = 8.5,
) -> Dict[int, List[Dict]]:
    # This initial sort creates a master list ranked by relevance.
    pois = sorted([p.copy() for p in city_pois], key=lambda x: score_poi(x, travel_style), reverse=True)
    
    center_lat = stay_coord[0] if stay_coord else sum(p["lat"] for p in pois) / len(pois)
    center_lon = stay_coord[1] if stay_coord else sum(p["lon"] for p in pois) / len(pois)
    
    remaining_pois = pois.copy()
    itinerary = {day: [] for day in range(1, days + 1)}

    for day in range(1, days + 1):
        time_used = 0.0
        cursor = {"lat": center_lat, "lon": center_lon, "name": "Start"}
        day_pois = []
        while remaining_pois:
            # ** THE FIX IS HERE **
            # This logic now sorts candidates by relevance (score) FIRST, and then by distance.
            # This ensures the most relevant places are chosen over closer, less relevant ones.
            candidates = sorted(
                [(p, haversine(cursor["lat"], cursor["lon"], p["lat"], p["lon"])) for p in remaining_pois],
                key=lambda x: (-score_poi(x[0], travel_style), x[1])
            )
            
            picked_poi = None
            for p, dist in candidates:
                travel_h = travel_time_hours(cursor, p)
                if time_used + travel_h + p.get("duration", 1) <= day_hours_budget:
                    picked_poi = p
                    break
            
            if not picked_poi: break

            travel_h = travel_time_hours(cursor, picked_poi)
            day_pois.append(picked_poi)
            time_used += travel_h + picked_poi.get("duration", 1)
            cursor = picked_poi
            remaining_pois = [r for r in remaining_pois if r["name"] != picked_poi["name"]]
        
        itinerary[day] = recompute_day_times(day_pois, start_time_str)

    return itinerary

# ------------------------------
# SIDEBAR & REACTIVE LOGIC
# ------------------------------
with st.sidebar:
    st.title("🤖 AI Tour Guide")
    st.markdown("Your trip plan updates automatically as you make changes.")
    
    selected_state = st.selectbox("State", list(POIS_BY_STATE.keys()))
    selected_city = st.selectbox("City", list(POIS_BY_STATE[selected_state].keys()))
    days = st.number_input("Number of days", 1, 14, 3)
    travel_style = st.selectbox("Travel style", ["cultural", "historical", "family", "adventure", "romantic", "spiritual", "relaxation"])
    start_time = st.text_input("Daily start time (HH:MM)", "09:00")
    stay_loc = st.text_input("Optional: Your stay's lat,lon", placeholder="e.g., 22.5726,88.3639")
    
    st.markdown("---")
    theme_choice = st.radio("Theme", ["light", "dark"], index=1 if st.session_state.theme == "dark" else 0)
    st.session_state.theme = theme_choice

current_params = {
    "state": selected_state,
    "city": selected_city,
    "days": days,
    "travel_style": travel_style,
    "start_time": start_time,
    "stay_loc": stay_loc
}

if current_params != st.session_state.last_params:
    st.session_state.last_params = current_params
    try:
        stay_coord = tuple(float(x.strip()) for x in stay_loc.split(",")) if stay_loc else None
        city_pois = POIS_BY_STATE[selected_state][selected_city]
        
        with st.spinner("✨ Your new itinerary is being crafted..."):
            itinerary = generate_itinerary(city_pois, days, travel_style, start_time, stay_coord)
        
        st.session_state.itinerary = itinerary
        st.session_state.selected_day = 1
        st.rerun()
    except Exception as e:
        st.error(f"Failed to generate itinerary: {e}")

# ------------------------------
# MAIN CONTENT: ITINERARY & MAP
# ------------------------------
if not st.session_state.itinerary:
    st.info("Your itinerary will appear here once generated. Try changing the options in the sidebar!")
else:
    col1, col2 = st.columns([2, 1.5])
    itinerary = st.session_state.itinerary
    with col1:
        st.header(f"Trip Itinerary for {current_params['city']}")
        day_tabs = [f"Day {d}" for d in itinerary.keys()]
        if st.session_state.selected_day not in itinerary:
            st.session_state.selected_day = 1
        
        selected_day_tab = st.selectbox("Select day", day_tabs, index=st.session_state.selected_day - 1)
        st.session_state.selected_day = int(selected_day_tab.split(" ")[1])
        day_acts = itinerary[st.session_state.selected_day]

        if not day_acts:
            st.warning(f"No activities could be scheduled for Day {st.session_state.selected_day}. Try increasing the number of days or changing your travel style.")
        else:
            for idx, poi in enumerate(day_acts):
                card_key = f"day{st.session_state.selected_day}_item{idx}"
                st.markdown("<div class='card'>", unsafe_allow_html=True)
                c1, c2, c3 = st.columns([1.5, 3.5, 0.8])
                with c1:
                    st.image(poi.get("image", placeholder_image_url(poi["name"])), width=160)
                with c2:
                    st.subheader(poi["name"])
                    tags = poi.get("tags", [])
                    if tags:
                        tag_html = "".join([f"<span class='tag-pill'>{tag.capitalize()}</span>" for tag in tags])
                        st.markdown(tag_html, unsafe_allow_html=True)
                    st.markdown(f"<div class='meta' style='margin-top: 8px;'>{poi.get('description','')}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='small'>🕒 <strong>{poi.get('duration',1)} hrs</strong> | ⏰ <strong>{poi.get('start_time','')} - {poi.get('end_time','')}</strong></div>", unsafe_allow_html=True)
                with c3:
                    if st.button("⬆️", key=f"up_{card_key}", help="Move up"):
                        if idx > 0:
                            day_acts[idx-1], day_acts[idx] = day_acts[idx], day_acts[idx-1]
                            itinerary[st.session_state.selected_day] = recompute_day_times(day_acts, start_time)
                            st.rerun()
                    if st.button("⬇️", key=f"down_{card_key}", help="Move down"):
                        if idx < len(day_acts) - 1:
                            day_acts[idx+1], day_acts[idx] = day_acts[idx], day_acts[idx+1]
                            itinerary[st.session_state.selected_day] = recompute_day_times(day_acts, start_time)
                            st.rerun()
                    if st.button("❌", key=f"remove_{card_key}", help="Remove"):
                        del day_acts[idx]
                        itinerary[st.session_state.selected_day] = recompute_day_times(day_acts, start_time)
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.header("Map & Utilities")
        day_list = itinerary.get(st.session_state.selected_day, [])
        if not day_list:
            st.info("No places to show on map for this day.")
        else:
            df_map = pd.DataFrame([{"order": i+1, "name": p["name"], "lat": p["lat"], "lon": p["lon"], "label": f"{i+1}. {p['name']}"} for i, p in enumerate(day_list)])
            try:
                import pydeck as pdk
                view_state = pdk.ViewState(latitude=df_map["lat"].mean(), longitude=df_map["lon"].mean(), zoom=11)
                st.pydeck_chart(pdk.Deck(
                    layers=[
                        pdk.Layer("PathLayer", [{"path": df_map[["lon", "lat"]].values.tolist()}], get_path="path", get_color=[0, 120, 200], width_min_pixels=3),
                        pdk.Layer("ScatterplotLayer", df_map, get_position=["lon", "lat"], get_radius=200, get_fill_color=[255, 100, 100], pickable=True),
                        pdk.Layer("TextLayer", df_map, get_position=["lon", "lat"], get_text="label", get_size=14, get_color=[255, 255, 255], get_alignment_baseline="'bottom'"),
                    ],
                    initial_view_state=view_state, tooltip={"html": "<b>{name}</b>"}
                ))
                if len(day_list) > 1:
                    origin = f"{day_list[0]['lat']},{day_list[0]['lon']}"
                    destination = f"{day_list[-1]['lat']},{day_list[-1]['lon']}"
                    waypoints = "|".join([f"{p['lat']},{p['lon']}" for p in day_list[1:-1]])
                    gmaps_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&waypoints={urllib.parse.quote(waypoints)}&travelmode=driving"
                    st.markdown(f'<a href="{gmaps_url}" target="_blank" style="text-decoration: none; display: inline-block; padding: 10px 15px; background-color: #4285F4; color: white; border-radius: 5px; text-align: center; width: 100%;">📍 Open Route in Google Maps</a>', unsafe_allow_html=True)
            except ImportError:
                st.warning("For a better map view, please install pydeck: pip install pydeck")
                st.map(df_map[["lat", "lon"]])
        
        st.markdown("---")
        st.subheader("Export")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("Export JSON", json.dumps(itinerary, indent=2), "itinerary.json", "application/json", use_container_width=True)
        with c2:
            flat_rows = [{"day": d, "place": p["name"], "start": p.get("start_time",""), "end": p.get("end_time",""), "duration_hrs": p.get("duration",1)} for d, pois in itinerary.items() for p in pois]
            st.download_button("Export CSV", pd.DataFrame(flat_rows).to_csv(index=False), "itinerary.csv", "text/csv", use_container_width=True)