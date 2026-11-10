# ThermoLoop AI — Data-Centre Workload Simulator

A public, interactive Streamlit application that generates synthetic data-centre workload telemetry and estimates IT power, generated heat, and recoverable waste-heat supply.

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Output schema

The downloadable CSV includes timestamps, workload profile, GPU/CPU utilisation, estimated active jobs, GPU/CPU/fixed IT power, total IT power, generated heat, cooling return temperature, temperature-grade factor, recoverable heat, unrecovered heat, and interval energy.

Important downstream ThermoLoop columns:
- `timestamp`
- `it_power_kw`
- `recoverable_heat_kwth`
- `recoverable_heat_energy_kwhth`
- `cooling_return_temp_c`

## Engineering model and limitations

The simulator is an aggregate synthetic scenario generator, not live telemetry or a validated data-centre digital twin.

- Fleet IT power is estimated from rated GPU/CPU fleet power, utilisation, and configurable idle fractions.
- Electrical IT power is converted to heat using a configurable heat fraction.
- Recoverable heat is reduced by a capture-efficiency factor and a simplified temperature-grade factor.
- The cooling return temperature is a workload-linked proxy, not a detailed cooling-loop model.
- The job count is a display estimate, not a scheduler simulation.
- It does not model PUE, individual server power curves, heat exchanger approach temperature, heat pump COP, or building demand.

Default parameters are illustrative. Cite and replace them with facility-specific or published values before making real-world performance claims. Keep all downstream power and energy units consistent: kW/kWth are rates; kWh/kWhth are interval energies.