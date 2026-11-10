import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="ThermoLoop | Data-Centre Workload Simulator", page_icon="♨️", layout="wide")

st.title("♨️ ThermoLoop AI — Data-Centre Workload Simulator")
st.caption("Synthetic workload → IT power → thermal output → recoverable waste-heat supply")
st.info(
    "This is a configurable synthetic engineering simulator, not a live data-centre telemetry feed. "
    "Its outputs are scenario data for ThermoLoop forecasting and control experiments."
)

PROFILES = {
    "Mixed AI workloads": {"level": 0.58, "daily": 0.10, "burst": 0.18, "cpu_ratio": 0.48},
    "GPU training cluster": {"level": 0.78, "daily": 0.04, "burst": 0.13, "cpu_ratio": 0.34},
    "Inference service": {"level": 0.43, "daily": 0.13, "burst": 0.22, "cpu_ratio": 0.55},
    "Batch / research jobs": {"level": 0.50, "daily": 0.18, "burst": 0.28, "cpu_ratio": 0.62},
    "Low utilisation": {"level": 0.20, "daily": 0.05, "burst": 0.08, "cpu_ratio": 0.42},
}

def smooth_noise(rng, n, scale=1.0):
    raw = rng.normal(0, scale, n)
    if n < 3:
        return raw
    return np.convolve(raw, np.array([0.2, 0.6, 0.2]), mode="same")

def simulate(cfg):
    rng = np.random.default_rng(cfg["seed"])
    n = int(cfg["hours"] * 60 / cfg["interval"])
    ts = pd.date_range(
        start=pd.Timestamp(cfg["start"]), periods=n, freq=f'{cfg["interval"]}min'
    )
    p = PROFILES[cfg["profile"]]
    hours = ts.hour.to_numpy() + ts.minute.to_numpy()/60
    day_phase = 2*np.pi*(hours-14)/24
    # The workload profile has a broad daily cycle, correlated variation and burst events.
    daily = p["daily"] * np.cos(day_phase)
    base = p["level"] + daily + smooth_noise(rng, n, 0.055)
    gpu = np.clip(base, 0.04, 0.98)
    cpu_base = p["cpu_ratio"]*gpu + (1-p["cpu_ratio"])*0.30
    cpu = np.clip(cpu_base + smooth_noise(rng, n, 0.045), 0.03, 0.95)

    # Add bursty job arrivals with a finite duration; use a smoothed pulse so transitions
    # are not instantaneous. Burst amplitude is bounded to keep utilisation physical.
    burst_signal = np.zeros(n)
    events = max(1, int(cfg["hours"] * cfg["burst_rate_per_day"] / 24))
    for _ in range(events):
        start_idx = int(rng.integers(0, max(1, n)))
        duration = max(1, int(rng.uniform(0.5, 2.5)*60/cfg["interval"]))
        end_idx = min(n, start_idx + duration)
        burst_signal[start_idx:end_idx] += rng.uniform(0.08, 0.24)
    gpu = np.clip(gpu + burst_signal, 0.03, 0.99)
    cpu = np.clip(cpu + 0.45*burst_signal, 0.02, 0.98)

    # A simple synthetic workload/job counter, not a scheduler-level queue model.
    job_count = np.maximum(
        0, np.round(cfg["max_concurrent_jobs"]*(0.12 + 0.72*gpu)
                    + rng.normal(0, cfg["max_concurrent_jobs"]*0.035, n))
    ).astype(int)

    # IT power model: fleet idle draw plus utilisation-dependent dynamic draw.
    # GPU/CPU powers are fleet-level nameplate values entered by the user.
    gpu_power = cfg["gpu_fleet_kw"] * (
        cfg["gpu_idle_fraction"] + (1-cfg["gpu_idle_fraction"])*np.power(gpu, 1.25)
    )
    cpu_power = cfg["cpu_fleet_kw"] * (
        cfg["cpu_idle_fraction"] + (1-cfg["cpu_idle_fraction"])*np.power(cpu, 1.15)
    )
    fixed_power = cfg["network_storage_kw"]
    it_power = gpu_power + cpu_power + fixed_power
    # Small measurement/model noise; power remains non-negative.
    it_power = np.maximum(0, it_power + rng.normal(0, cfg["power_noise_fraction"], n)*it_power)

    # Electrical input to IT equipment is treated as heat within the selected boundary.
    # A small fraction is excluded for energy leaving the boundary (e.g. exported work).
    heat_generated = it_power * cfg["heat_fraction"]
    # Return temperature is a simplified proxy for heat grade, not a CFD/cooling model.
    return_temp = (
        cfg["return_temp_base_c"] + cfg["return_temp_rise_c"]*gpu
        + smooth_noise(rng, n, 0.35)
    )
    return_temp = np.clip(return_temp, cfg["return_temp_min_c"], cfg["return_temp_max_c"])
    temp_factor = np.clip(
        (return_temp-cfg["minimum_useful_temp_c"]) /
        max(0.1, cfg["full_grade_temp_c"]-cfg["minimum_useful_temp_c"]), 0, 1
    )
    recoverable_heat = heat_generated * cfg["recovery_efficiency"] * temp_factor
    rejected_heat = np.maximum(0, heat_generated-recoverable_heat)

    df = pd.DataFrame({
        "timestamp": ts,
        "workload_profile": cfg["profile"],
        "gpu_utilization_pct": np.round(gpu*100, 2),
        "cpu_utilization_pct": np.round(cpu*100, 2),
        "active_jobs_estimate": job_count,
        "gpu_it_power_kw": np.round(gpu_power, 3),
        "cpu_it_power_kw": np.round(cpu_power, 3),
        "fixed_it_power_kw": np.round(np.full(n, fixed_power), 3),
        "it_power_kw": np.round(it_power, 3),
        "heat_generated_kwth": np.round(heat_generated, 3),
        "cooling_return_temp_c": np.round(return_temp, 2),
        "temperature_grade_factor": np.round(temp_factor, 3),
        "recoverable_heat_kwth": np.round(recoverable_heat, 3),
        "unrecovered_heat_kwth": np.round(rejected_heat, 3),
    })
    df["interval_energy_kwh"] = np.round(df["it_power_kw"]*cfg["interval"]/60, 4)
    df["recoverable_heat_energy_kwhth"] = np.round(df["recoverable_heat_kwth"]*cfg["interval"]/60, 4)
    return df

with st.sidebar:
    st.header("Simulation settings")
    profile = st.selectbox("Workload scenario", list(PROFILES.keys()), index=0)
    hours = st.select_slider("Simulation duration", options=[24, 48, 72, 168, 336], value=48)
    interval = st.selectbox("Time resolution", [5, 15, 30, 60], index=2)
    start = st.date_input("Start date", value=datetime(2026, 11, 10).date())
    seed = st.number_input("Random seed", min_value=0, max_value=999999, value=42, step=1)
    st.divider()
    st.subheader("Data-centre fleet")
    gpu_count = st.number_input("GPU count", 1, 100000, 256, step=16)
    gpu_kw_each = st.number_input("Rated GPU power (kW each)", 0.1, 5.0, 0.70, 0.05)
    cpu_servers = st.number_input("CPU server count", 1, 100000, 64, step=4)
    cpu_kw_each = st.number_input("Rated CPU server power (kW each)", 0.1, 5.0, 0.50, 0.05)
    network_storage_kw = st.number_input("Network + storage IT power (kW)", 0.0, 10000.0, 35.0, 5.0)
    max_jobs = st.number_input("Maximum concurrent jobs (display estimate)", 1, 100000, 180, step=10)
    burst_rate = st.slider("Burst events per day", 0, 80, 12)
    st.divider()
    st.subheader("Thermal assumptions")
    heat_fraction = st.slider("IT power converted to heat (%)", 90, 100, 98)/100
    recovery = st.slider("Heat capture efficiency (%)", 10, 95, 70)/100
    return_base = st.slider("Cooling return temperature baseline (°C)", 20, 55, 30)
    return_rise = st.slider("Temperature rise at full GPU load (°C)", 0, 20, 8)
    min_useful = st.slider("Minimum useful source temperature (°C)", 20, 60, 30)
    full_grade = st.slider("Full temperature-grade threshold (°C)", 25, 80, 45)
    noise_pct = st.slider("IT power noise (%)", 0, 10, 2)/100
    generate = st.button("Generate / regenerate simulation", type="primary", use_container_width=True)

cfg = {
    "profile": profile, "hours": hours, "interval": interval,
    "start": datetime.combine(start, datetime.min.time()), "seed": int(seed),
    "gpu_fleet_kw": gpu_count*gpu_kw_each, "cpu_fleet_kw": cpu_servers*cpu_kw_each,
    "network_storage_kw": float(network_storage_kw), "max_concurrent_jobs": int(max_jobs),
    "burst_rate_per_day": int(burst_rate), "gpu_idle_fraction": 0.28,
    "cpu_idle_fraction": 0.35, "heat_fraction": heat_fraction,
    "recovery_efficiency": recovery, "return_temp_base_c": return_base,
    "return_temp_rise_c": return_rise, "return_temp_min_c": 15,
    "return_temp_max_c": 75, "minimum_useful_temp_c": min_useful,
    "full_grade_temp_c": max(full_grade, min_useful+0.1),
    "power_noise_fraction": noise_pct,
}

if "thermoloop_df" not in st.session_state or generate:
    st.session_state.thermoloop_df = simulate(cfg)
    st.session_state.thermoloop_cfg = cfg

df = st.session_state.thermoloop_df
# Recompute when settings change even if user hasn't clicked; explicit button remains useful
# as a clear regenerate action. Store config signature to avoid stale controls.
signature = tuple((k, str(v)) for k, v in cfg.items())
if st.session_state.get("signature") != signature:
    st.session_state.thermoloop_df = simulate(cfg)
    st.session_state.thermoloop_cfg = cfg
    st.session_state.signature = signature
    df = st.session_state.thermoloop_df

total_it_kwh = (df["it_power_kw"]*interval/60).sum()
total_recoverable = df["recoverable_heat_energy_kwhth"].sum()
mean_gpu = df["gpu_utilization_pct"].mean()
peak_it = df["it_power_kw"].max()
mean_recoverable = df["recoverable_heat_kwth"].mean()

m1,m2,m3,m4 = st.columns(4)
m1.metric("Average GPU utilisation", f"{mean_gpu:.1f}%")
m2.metric("Peak IT power", f"{peak_it:,.1f} kW")
m3.metric("Mean recoverable heat", f"{mean_recoverable:,.1f} kWth")
m4.metric("Recoverable heat energy", f"{total_recoverable:,.0f} kWhth")

tab1, tab2, tab3, tab4 = st.tabs(["Live simulation trace", "Thermal analysis", "Data preview", "Model assumptions"])
with tab1:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.timestamp, y=df.gpu_utilization_pct, name="GPU utilisation (%)", yaxis="y"))
    fig.add_trace(go.Scatter(x=df.timestamp, y=df.cpu_utilization_pct, name="CPU utilisation (%)", yaxis="y"))
    fig.update_layout(title="Synthetic workload utilisation", yaxis_title="Utilisation (%)", hovermode="x unified", height=390)
    st.plotly_chart(fig, use_container_width=True)
    pfig = go.Figure()
    pfig.add_trace(go.Scatter(x=df.timestamp, y=df.it_power_kw, name="IT power (kW)"))
    pfig.add_trace(go.Scatter(x=df.timestamp, y=df.recoverable_heat_kwth, name="Recoverable heat (kWth)"))
    pfig.update_layout(title="IT electrical power and recoverable thermal power", yaxis_title="Power (kW / kWth)", hovermode="x unified", height=390)
    st.plotly_chart(pfig, use_container_width=True)
with tab2:
    c1,c2 = st.columns(2)
    with c1:
        fig = px.scatter(df, x="cooling_return_temp_c", y="recoverable_heat_kwth",
                         color="gpu_utilization_pct", title="Heat recovery vs cooling return temperature")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.histogram(df, x="recoverable_heat_kwth", nbins=30, title="Recoverable heat distribution")
        st.plotly_chart(fig, use_container_width=True)
    st.caption("Recoverable heat is lower than generated heat when capture efficiency or temperature-grade factor is below 100%.")
with tab3:
    st.dataframe(df.head(100), use_container_width=True, hide_index=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download full simulation CSV", csv,
                       file_name="thermoloop_datacenter_workload.csv", mime="text/csv")
with tab4:
    st.markdown("""
**Power model (fleet-level approximation)**

- GPU fleet power = rated GPU fleet power × [idle fraction + (1 − idle fraction) × GPU utilisation¹·²⁵]
- CPU fleet power = rated CPU fleet power × [idle fraction + (1 − idle fraction) × CPU utilisation¹·¹⁵]
- IT power = GPU power + CPU power + fixed network/storage power
- Generated heat = IT power × heat fraction
- Recoverable heat = generated heat × capture efficiency × temperature-grade factor

**Important limitations**

1. Utilisation is not treated as a direct measurement of power. A configurable nonlinear power approximation is used.
2. This is an aggregate fleet model. It does not simulate individual servers, job scheduling, GPU memory bottlenecks, cooling plant dynamics or data-centre PUE in detail.
3. Cooling return temperature is a simplified workload-linked proxy. It is not a validated liquid-cooling or air-cooling thermodynamic model.
4. Recoverable heat is a thermal-power estimate in **kWth**. Interval thermal energy is in **kWhth**.
5. The simulator does not model a heat pump or building demand. Those belong to the downstream ThermoLoop modules.
6. The 98% heat fraction, 70% capture efficiency and other defaults are illustrative assumptions. Replace them with cited facility data when available.
""")
    assumptions = pd.DataFrame([
        ["GPU rated fleet power", cfg["gpu_fleet_kw"], "kW"],
        ["CPU rated fleet power", cfg["cpu_fleet_kw"], "kW"],
        ["Fixed network/storage power", cfg["network_storage_kw"], "kW"],
        ["IT-to-heat fraction", heat_fraction, "fraction"],
        ["Heat capture efficiency", recovery, "fraction"],
        ["Minimum useful source temperature", min_useful, "°C"],
        ["Full temperature-grade threshold", cfg["full_grade_temp_c"], "°C"],
    ], columns=["Parameter", "Value", "Unit"])
    st.dataframe(assumptions, use_container_width=True, hide_index=True)

st.divider()
st.caption("ThermoLoop AI • Synthetic data generator for research and hackathon prototyping • Not operational control software")
