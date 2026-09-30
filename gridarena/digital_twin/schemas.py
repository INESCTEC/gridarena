"""Pydantic schemas for Digital Twin configuration, events, results and metrics."""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from gridarena.schemas.types import Phase


# ── Reusable measurement schema (compatible with existing Measurements) ──


class StreamedMeasurement(BaseModel):
    """A single streamed measurement, field-compatible with the existing Measurements schema."""

    node_id: str
    phase: Optional[Phase] = None
    datetime: str
    power_active: float
    power_reactive: float
    voltage_magnitude: float
    voltage_angle: float = 0.0


class StreamedMeasurementBatch(BaseModel):
    """A batch of streamed measurements for a grid, compatible with MeasurementsData."""

    grid_id: str
    timestamp: str
    measurements: List[StreamedMeasurement]


# ── Connector configuration ──


class SourceConfig(BaseModel):
    source_type: Literal["http"] = "http"
    url: str
    method: Literal["GET", "POST"] = "GET"
    headers: Dict[str, str] = Field(default_factory=dict)
    query_params: Dict[str, str] = Field(default_factory=dict)
    body_template: Optional[Dict[str, Any]] = None
    auth_type: Literal["none", "bearer", "token", "api_key", "basic"] = "none"
    secret_ref: Optional[str] = Field(
        None,
        description="Name of the environment variable holding the secret (token, API key, or basic credentials).",
    )
    secret_header: Optional[str] = Field(
        None,
        description="Header name for the secret (e.g. 'Authorization', 'X-Api-Key'). Defaults based on auth_type.",
    )
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    retry_count: int = Field(default=3, ge=0, le=10)


# ── Field mapping ──


class FieldMapping(BaseModel):
    timestamp: str = Field(..., description="Path to the timestamp field in the source payload.")
    measurements: str = Field(..., description="Path to the measurements array in the source payload.")
    node_id: str = Field(..., description="Path to node_id within each measurement.")
    phase: Optional[str] = Field(None, description="Path to phase within each measurement.")
    active_power: str = Field(..., description="Path to active power within each measurement.")
    reactive_power: str = Field(..., description="Path to reactive power within each measurement.")
    voltage_magnitude: str = Field(..., description="Path to voltage magnitude within each measurement.")
    voltage_angle: Optional[str] = Field(None, description="Path to voltage angle within each measurement.")


# ── Per-node field mapping (for per-node mode) ──


class NodeFieldMapping(BaseModel):
    """Mapping paths for a single node's API response to GridArena fields."""

    timestamp: str = Field("data[0].datetime", description="Path to timestamp in the node's API response.")
    active_power: Optional[str] = Field(None, description="Path to active power value.")
    reactive_power: Optional[str] = Field(None, description="Path to reactive power value.")
    voltage_magnitude: Optional[str] = Field(None, description="Path to voltage magnitude value.")
    voltage_angle: Optional[str] = Field(None, description="Path to voltage angle value.")
    active_power_factor: float = Field(default=1.0, description="Multiplicative factor applied to active power.")
    reactive_power_factor: float = Field(default=1.0, description="Multiplicative factor applied to reactive power.")
    voltage_magnitude_factor: float = Field(default=1.0, description="Multiplicative factor applied to voltage magnitude.")


class NodeAssignment(BaseModel):
    """Configuration for fetching data for one grid node from the external API."""

    node_id: str
    phase: Phase = "R"
    query_params: Dict[str, str] = Field(default_factory=dict)
    update_interval_seconds: int = Field(default=60, ge=5, le=86400)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    mapping: NodeFieldMapping = NodeFieldMapping()


# ── Power-flow configuration ──


class PowerFlowConfig(BaseModel):
    phase: Phase = "R"
    voltage_ref: float = Field(default=230.0, gt=0.0)


# ── Digital twin CRUD schemas ──


class DigitalTwinCreate(BaseModel):
    grid_id: str
    name: str = ""
    description: str = ""
    update_interval_seconds: int = Field(default=60, ge=5, le=86400)
    broker_type: Literal["redis"] = "redis"
    broker_topic: Optional[str] = None
    source_config: SourceConfig
    field_mapping: Optional[FieldMapping] = None
    node_assignments: Optional[List[NodeAssignment]] = None
    powerflow_config: PowerFlowConfig = PowerFlowConfig()


class DigitalTwinUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    update_interval_seconds: Optional[int] = Field(None, ge=5, le=86400)
    source_config: Optional[SourceConfig] = None
    field_mapping: Optional[FieldMapping] = None
    powerflow_config: Optional[PowerFlowConfig] = None


class DigitalTwinStatus(BaseModel):
    digital_twin_id: str
    grid_id: str
    name: str
    description: str
    status: Literal["created", "running", "stopped", "failed"]
    update_interval_seconds: int
    broker_type: str
    broker_topic: str
    source_config: SourceConfig
    field_mapping: FieldMapping
    powerflow_config: PowerFlowConfig
    created_at: str
    updated_at: str
    last_run_at: Optional[str] = None
    last_error: Optional[str] = None


# ── Events ──


class DigitalTwinEvent(BaseModel):
    event_id: int
    digital_twin_id: str
    event_type: str
    message: str
    details: Optional[Dict[str, Any]] = None
    created_at: str


# ── Results / Metrics ──


class DigitalTwinResult(BaseModel):
    result_id: int
    digital_twin_id: str
    timestamp: str
    measurements_count: int = 0
    missing_measurements: int = 0
    invalid_measurements: int = 0
    convergence_status: str = "unknown"
    voltage_mae: Optional[float] = None
    voltage_rmse: Optional[float] = None
    max_voltage_error: Optional[float] = None
    active_power_error: Optional[float] = None
    reactive_power_error: Optional[float] = None
    execution_time_ms: Optional[float] = None
    powerflow_algorithm: str = "backward_forward_sweep"
    details: Optional[Dict[str, Any]] = None
    created_at: str


# ── Validation helpers ──


class ValidateFieldMappingRequest(BaseModel):
    source_sample: Dict[str, Any]
    field_mapping: FieldMapping
    grid_id: str


class ValidateFieldMappingResponse(BaseModel):
    success: bool
    mapped_payload: Optional[StreamedMeasurementBatch] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    invalid_nodes: List[str] = Field(default_factory=list)
    invalid_phases: List[str] = Field(default_factory=list)
    type_errors: List[str] = Field(default_factory=list)
    duplicate_measurements: List[str] = Field(default_factory=list)


class TestSourceResponse(BaseModel):
    success: bool
    status_code: Optional[int] = None
    raw_payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class LatestStateResponse(BaseModel):
    digital_twin_id: str
    grid_id: str
    status: str
    last_run_at: Optional[str] = None
    latest_measurements: Optional[StreamedMeasurementBatch] = None
    latest_result: Optional[DigitalTwinResult] = None
