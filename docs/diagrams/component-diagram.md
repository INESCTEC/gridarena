# Component Diagram

High-level view of gridarena's runtime components: the FastAPI application and
its routers, the shared database layer, the background job workers, the
digital twin subsystem, and the LLM chat subsystem. See [Architecture](../architecture.md)
for the accompanying prose description.

```mermaid
flowchart TB
    Client[Browser UI / API Client]

    subgraph API["FastAPI Application (gridarena/app.py)"]
        direction TB
        subgraph CoreRouters["Grid &amp; Measurement Routers"]
            Grid[grid]
            MVGrid[mv_grid]
            Measurements[measurements]
            Historical[historical]
            PowerFlow[powerflow]
        end
        subgraph BenchmarkRouters["Benchmark Routers"]
            PhaseID[phase_identification_benchmark]
            Topology[topology_discovery_benchmark]
            StateEst[state_estimation_benchmark]
            VoltageCtrl[voltage_control_benchmark]
        end
        subgraph JobRouters["Background-Job Routers"]
            RLRouter[rl]
            Diffusion[diffusion]
            PFDatagen[pf_datagen]
        end
        DigitalTwinRouter[digital_twin]
        Chat[chat]
        Offline[offline_scenarios]
    end

    subgraph DBLayer["Database Layer"]
        Pool[psycopg_pool.ConnectionPool]
    end
    PG[(PostgreSQL)]

    subgraph Workers["ProcessPoolExecutor Workers"]
        RLWorker[RL training worker]
        DiffWorker[Diffusion training worker]
        PFWorker[PF scenario-gen worker]
    end

    subgraph Twin["Digital Twin Subsystem"]
        Runner[runner.py]
        Broker[broker.py]
        Connector[connector.py]
    end
    Redis[(Redis)]
    ExtSource[/External Data Source/]

    subgraph LLM["LLM Chat Subsystem"]
        RAG[RAG / Chroma vector store]
    end
    ExtLLM[/External LLM Backend/]

    Client -->|HTTP| API

    CoreRouters --> DBLayer
    BenchmarkRouters --> DBLayer
    JobRouters --> DBLayer
    DigitalTwinRouter --> DBLayer
    Chat --> DBLayer
    Offline --> DBLayer
    DBLayer --> PG

    RLRouter --> RLWorker
    Diffusion --> DiffWorker
    PFDatagen --> PFWorker
    RLWorker --> DBLayer
    DiffWorker --> DBLayer
    PFWorker --> DBLayer

    DigitalTwinRouter --> Runner
    Runner --> Broker
    Broker --> Redis
    Runner --> Connector
    Connector --> ExtSource
    Runner --> PowerFlow

    Chat --> RAG
    Chat --> ExtLLM
```
