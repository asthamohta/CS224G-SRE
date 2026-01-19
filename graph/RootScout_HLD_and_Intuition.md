# RootScout: High-Level Design (HLD) & Intuition

## 1. The Core Intuition: "The Detective & The Blueprint"
To understand RootScout, think of a burning building.



* **The Problem:** A fire alarm goes off (Alert), but the building has 50 rooms.
* **The "Old" Way:** A detective (AI) runs into every single room to find the fire. This is slow, expensive, and the detective often gets lost (hallucinates).
* **The RootScout Way:**
    1.  **The Blueprint (The Graph):** Before entering, the detective looks at a blueprint. It shows the alarm was triggered in the Kitchen, but the gas pipe feeding the Kitchen comes from the Basement.
    2.  **The Investigation (The Agent):** The detective ignores the Bedrooms and Attic. They go straight to the **Basement** to check the pipes.

### Visual Comparison
```mermaid
flowchart LR
    subgraph "Without RootScout (Chaos)"
    A[Alert!] --> B{AI Checks Everything?}
    B --> C[Check Frontend Logs]
    B --> D[Check Database Logs]
    B --> E[Check Payment Logs]
    B --> F[Check Auth Logs]
    style B fill:#f9f,stroke:#333
    end

    subgraph "With RootScout (Focus)"
    G[Alert!] --> H{Graph Filter}
    H -->|Trace says error came from Payment| I[AI Checks ONLY Payment Service]
    I --> J[Found Root Cause]
    style H fill:#bbf,stroke:#333
    style I fill:#bfb,stroke:#333
    end