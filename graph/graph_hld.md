## 2. High-Level Design (HLD)

### Architecture Diagram
RootScout is a pipeline that transforms raw telemetry into a structured investigation report.

```mermaid
graph TD
    %% LAYER 1: DATA SOURCES
    subgraph Data_Sources
        OTEL[OpenTelemetry Traces]
        GIT[GitHub Webhooks]
        LOGS[Service Logs]
    end

    %% LAYER 2: THE BRAIN (Graph Engine)
    subgraph Core_Engine
        GB[Graph Builder]
        NX[(NetworkX Graph)]
        FI[Fault Isolation Module]
    end

    %% LAYER 3: THE AGENT
    subgraph Reasoning_Layer
        AGENT[AI SRE Agent]
        TOOLS[Context Tools]
    end

    %% FLOW
    OTEL -->|Stream Spans| GB
    GIT -->|Stream Diffs| GB
    GB -->|Build Nodes/Edges| NX
    
    %% INCIDENT FLOW
    Alert_Trigger -->|Service X is Slow| FI
    NX -->|Query Dependencies| FI
    FI -->|Identify Leaf Node: Service Y| AGENT
    
    %% INVESTIGATION
    AGENT -->|Fetch Logs for Service Y| TOOLS
    AGENT -->|Fetch Commits for Service Y| TOOLS
    LOGS --> TOOLS
    GIT --> TOOLS
    
    %% OUTPUT
    AGENT -->|Generate| REPORT[Final Incident Report]
    
    style AGENT fill:#f96,stroke:#333,stroke-width:2px
    style NX fill:#69f,stroke:#333,stroke-width:2px