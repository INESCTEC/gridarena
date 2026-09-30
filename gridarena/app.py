"""Main API file"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import gridarena.routers as rt

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def _ensure_benchmark_tables():
    """Create benchmark-related tables once at startup."""
    import gridarena.database as db
    conn, cursor = db.get_db_connection()
    try:
        db.create_anon_map_database(cursor)
        db.create_phase_guesses_database(cursor)
        db.create_topology_guesses_database(cursor)
        db.create_voltage_timestamp_map_table(cursor)
        db.create_vc_guesses_database(cursor)
        db.create_voltage_control_solutions(cursor)
        db.create_base_tables(cursor)
        db.create_state_estimates_table(cursor)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS "GridAnonymisedMapping" (
                grid_id TEXT PRIMARY KEY,
                anonymised_grid_key TEXT UNIQUE NOT NULL
            )
        """)
        conn.commit()
    except Exception:
        logger.error("Failed to ensure benchmark tables exist", exc_info=True)
        conn.rollback()
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import gridarena.database as db
    from gridarena.diffusion.run_manager import diffusion_registry
    from gridarena.llm import init_rag
    from gridarena.pf_datagen.run_manager import pf_datagen_registry
    from gridarena.rl.run_manager import registry

    from gridarena.digital_twin.runner import dt_runner
    from gridarena.digital_twin.scenario_runner import scenario_runner

    _ensure_benchmark_tables()  # also warms the connection pool before the first request
    init_rag()
    registry.startup()
    diffusion_registry.startup()
    pf_datagen_registry.startup()
    yield
    dt_runner.shutdown()
    scenario_runner.shutdown()
    registry.shutdown()
    diffusion_registry.shutdown()
    pf_datagen_registry.shutdown()
    db.close_pool()


app = FastAPI(
    title="Low Voltage Grid Play Environment",
    description="LVGridPlay is a simulation and analytics API for low-voltage electrical \
                distribution grids.It allows users to upload or define grid topologies, execute \
                power flow simulations under various operating conditions, and access historical \
                simulation results for further analysis or forecasting. The API supports grid \
                updates, and enables integration with energy management algorithms.",
    version="0.1",
    lifespan=lifespan,
    contact={
        "name": "INESCTEC - Centro de Produção Energia e Sistemas (CPES)",
        "url": "https://www.inesctec.pt/",
        "email": "david.lima@inesctec.pt, goncalo.cunha@inesctec.pt",
    },
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(rt.grid.router, prefix="/grid", tags=["Grid"])
app.include_router(rt.historical.router, prefix="/historical", tags=["Historical"])
app.include_router(rt.measurements.router, prefix="/measurements", tags=["Measurements"])
app.include_router(rt.powerflow.router, prefix="/powerflow", tags=["Algorithm"])
app.include_router(
    rt.phase_identification_benchmark.router,
    prefix="/phase_identification_benchmark",
    tags=["Phase Identification Benchmark"],
)
app.include_router(
    rt.topology_discovery_benchmark.router,
    prefix="/topology_discovery_benchmark",
    tags=["Topology Discovery Benchmark"],
)
app.include_router(
    rt.state_estimation_benchmark.router,
    prefix="/state_estimation_benchmark",
    tags=["State Estimation Benchmark"],
)
app.include_router(
    rt.voltage_control_benchmark.router,
    prefix="/voltage_control_benchmark",
    tags=["Voltage Control Benchmark"],
)
app.include_router(rt.chat.router, prefix="/chat", tags=["Chat"])
app.include_router(rt.rl.router, prefix="/rl", tags=["Reinforcement Learning"])
app.include_router(rt.diffusion.router, prefix="/diffusion", tags=["Diffusion Models"])
app.include_router(rt.mv_grid.router, prefix="/mv_grid", tags=["MV Grid"])
app.include_router(rt.digital_twin.router, prefix="/digital-twins", tags=["Digital Twin"])
app.include_router(rt.offline_scenario.router, prefix="/offline-scenarios", tags=["Offline Scenarios"])
app.include_router(rt.pf_datagen.router, prefix="/pf-datagen", tags=["PF Data Generation"])

_cors_env = os.getenv("CORS_ORIGINS")
origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    import gridarena.database as db
    from gridarena.diffusion.run_manager import diffusion_registry
    from gridarena.pf_datagen.run_manager import pf_datagen_registry
    from gridarena.rl.run_manager import registry as rl_registry

    stats = {"n_lv_grids": 0, "n_mv_grids": 0, "n_historical_databases": 0, "n_active_runs": 0}
    try:
        conn, cursor = db.get_db_connection()
        try:
            db.create_mv_database(conn, cursor)
            db.create_historical_data_tables(cursor)
            cursor.execute("SELECT COUNT(*) FROM grids")
            stats["n_lv_grids"] = cursor.fetchone()[0] or 0
            cursor.execute('SELECT COUNT(*) FROM "MVGrid"')
            stats["n_mv_grids"] = cursor.fetchone()[0] or 0
            cursor.execute('SELECT COUNT(*) FROM "HistoricalDatabase"')
            stats["n_historical_databases"] = cursor.fetchone()[0] or 0
        finally:
            conn.close()
    except Exception:
        logger.warning("Failed to load home page grid/database stats", exc_info=True)

    try:
        active = {"queued", "running"}
        stats["n_active_runs"] = (
            sum(1 for r in rl_registry.list_runs() if r.status in active)
            + sum(1 for r in diffusion_registry.list_runs() if r.status in active)
            + sum(1 for r in pf_datagen_registry.list_runs() if r.status in active)
        )
    except Exception:
        logger.warning("Failed to load home page active-run stats", exc_info=True)

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "title": "Grid",
            "active": "home",
            "stats": stats,
        },
    )
