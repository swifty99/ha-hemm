"""Constants for the HEMM integration."""

from enum import StrEnum

DOMAIN = "hemm"

# Config keys
CONF_NAME = "name"
CONF_HORIZON_HOURS = "horizon_hours"
CONF_MAX_ITERATIONS = "max_iterations"
CONF_PRICE_ADAPTER = "price_adapter"
CONF_SOLVER_BACKEND = "solver_backend"

# Sub-entry config keys
CONF_DEVICE_TYPE = "device_type"
CONF_DEVICE_NAME = "device_name"
CONF_TIER = "tier"
CONF_SAFE_DEFAULT_SCRIPT = "safe_default_script"
CONF_SAFE_DEFAULT_VERIFY_ENTITY = "safe_default_verify_entity"
CONF_SAFE_DEFAULT_VERIFY_EXPECTED = "safe_default_verify_expected"
CONF_SAFE_DEFAULT_VERIFY_TIMEOUT = "safe_default_verify_timeout"

# Room-specific
CONF_FLOOR_AREA_M2 = "floor_area_m2"
CONF_INSULATION_CLASS = "insulation_class"
CONF_THERMAL_MASS = "thermal_mass_kwh_per_k"
CONF_U_VALUE = "u_value_w_per_m2k"
CONF_WINDOW_AREA_M2 = "window_area_m2"
CONF_SOUTH_FACING = "south_facing_windows"

# ThermostatLoad-specific
CONF_MAX_POWER_KW = "max_power_kw"
CONF_HYSTERESIS_K = "hysteresis_k"

# HeatPump-specific
CONF_VENDOR_MODEL = "vendor_model"
CONF_MIN_MODULATION_PCT = "min_modulation_pct"
CONF_DEFROST_LOCKOUT_MIN = "defrost_lockout_minutes"

# WaterHeater-specific
CONF_VOLUME_LITERS = "volume_liters"
CONF_STANDBY_LOSS_W = "standby_loss_w"
CONF_LOSS_COEFFICIENT = "loss_coefficient_w_per_k"

# Battery-specific
CONF_CAPACITY_KWH = "capacity_kwh"
CONF_MAX_CHARGE_KW = "max_charge_kw"
CONF_MAX_DISCHARGE_KW = "max_discharge_kw"
CONF_CHARGE_EFFICIENCY = "charge_efficiency"
CONF_DISCHARGE_EFFICIENCY = "discharge_efficiency"
CONF_MIN_SOC_PCT = "min_soc_pct"
CONF_MAX_SOC_PCT = "max_soc_pct"

# PVForecast-specific
CONF_PEAK_POWER_KWP = "peak_power_kwp"
CONF_AZIMUTH_DEG = "azimuth_deg"
CONF_TILT_DEG = "tilt_deg"
CONF_FORECAST_ADAPTER = "forecast_adapter"
CONF_FORECAST_ENTITY = "forecast_entity"

# EVCharger-specific
CONF_MIN_CHARGE_KW = "min_charge_kw"
CONF_PHASES = "phases"
CONF_PLUG_STATE_ENTITY = "plug_state_entity"
CONF_SOC_ENTITY = "soc_entity"
CONF_BATTERY_CAPACITY_KWH = "battery_capacity_kwh"

# Defaults
DEFAULT_NAME = "HEMM"
DEFAULT_HORIZON_HOURS = 24
DEFAULT_MAX_ITERATIONS = 50
DEFAULT_PRICE_ADAPTER = "template"
DEFAULT_SOLVER_BACKEND = "milp_central"

# Solver backend choices
SOLVER_BACKENDS = ["milp_central", "distributed"]

# Price adapter choices
PRICE_ADAPTERS = ["template", "solcast", "forecast_solar"]

# Forecast adapter choices (for PV sub-entries)
FORECAST_ADAPTERS = ["solcast", "forecast_solar", "template"]

# Tested HA version (set at build time / release)
TESTED_HA_VERSION = "2025.4.0"


class DeviceType(StrEnum):
    """Device types matching hemm core ManifestType."""

    ROOM = "room"
    THERMOSTAT_LOAD = "thermostat_load"
    HEAT_PUMP = "heat_pump"
    WATER_HEATER = "water_heater"
    BATTERY = "battery"
    PV_FORECAST = "pv_forecast"
    EV_CHARGER = "ev_charger"


class ConfigTier(StrEnum):
    """Configuration difficulty tiers."""

    BEGINNER = "beginner"
    ADVANCED = "advanced"
    PRO = "pro"


# Which device types support pro mode (all support beginner; 5 support pro)
DEVICE_PRO_SUPPORT: set[str] = {
    DeviceType.HEAT_PUMP,
    DeviceType.WATER_HEATER,
    DeviceType.BATTERY,
    DeviceType.PV_FORECAST,
    DeviceType.EV_CHARGER,
}
