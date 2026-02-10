# HTTP/2 Flow Control Delay Experiment Tool

This project provides a web-based interface to run HTTP/2 flow control experiments and visualize the results in real-time. It allows you to simulate delayed `WINDOW_UPDATE` frames and observe the behavior of the server and client using both application-level logs and packet-level captures (tcpdump).

## Features

- **Web UI**: Configure experiment parameters (host, IP, delay, start threshold, etc.) and control execution.
- **Real-time Visualization**:
  - Live streaming of HTTP/2 client logs (stdout/stderr).
  - Live streaming of `tcpdump` output.
- **Packet Capture**: Automatically records a `.pcap` file for each run, downloadable from the UI.
- **Dockerized**: Easy deployment with `docker-compose`.

## Prerequisites

- Docker and Docker Compose installed.
- **Privileged Access**: The container needs `NET_ADMIN` and `NET_RAW` capabilities to run `tcpdump`.

## Usage

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/NolanKiwi/h2-timeout-test.git
    cd h2-timeout-test
    ```

2.  **Start the application**:
    ```bash
    docker-compose up --build
    ```

3.  **Access the Web UI**:
    Open your browser and navigate to `http://localhost:3000`.

4.  **Run an Experiment**:
    - Enter the target **Host** (e.g., `testme2.akamaized.net`).
    - (Optional) Enter a specific **Target IP** to connect to (while keeping the Host as SNI).
    - Set **Delay** (seconds) and **Start After Bytes**.
    - Click **Start**.
    - Watch the live logs in the dual terminal panes.
    - Click **Stop** to end the experiment.
    - Click **Download PCAP** to get the packet capture.

## Configuration Options

-   `--host`: Domain name for TLS SNI and HTTP/2 `:authority`.
-   `--ip`: (Optional) Specific IP address to connect to via TCP.
-   `--port`: Target port (default: 443).
-   `--path`: HTTP/2 path to request (default: `/`).
-   `--range`: HTTP Range header (default: `bytes=0-`).
-   `--delay`: Duration to delay `WINDOW_UPDATE` frames (seconds).
-   `--start-after-bytes`: Byte threshold to trigger the delay.
-   `--ping-interval`: Interval for HTTP/2 PING frames (seconds).

## Architecture

-   **Backend**: Python FastAPI. Manages subprocesses (`h2_simulate.py`, `tcpdump`) and streams output via WebSockets.
-   **Frontend**: React + TypeScript (Vite). Uses `xterm.js` for terminal rendering.
-   **Container**: Runs based on `python:3.11-slim`, installing `tcpdump` and `libpcap`.

## Security & Safety

-   **Input Validation**: Inputs are sanitized to prevent shell injection. Subprocesses are executed with argument lists, not `shell=True`.
-   **Resource Limits**: Max delay and runtime are capped to prevent runaway processes.
-   **Isolation**: Runs inside a Docker container.

## Troubleshooting

-   **Permission Denied (tcpdump)**: Ensure the container is running with `--cap-add=NET_ADMIN --cap-add=NET_RAW` or in `privileged` mode.
-   **Connection Errors**: Verify the Target IP accepts traffic for the given Host (SNI). HTTP/2 (ALPN `h2`) must be supported.

## Test Plan

1.  **Baseline (No Delay)**:
    -   Set Delay = 0.
    -   Start run.
    -   Verify immediate download completion in h2 logs.
    -   Verify PCAP contains valid traffic.

2.  **Flow Control Delay**:
    -   Set Delay = 30, Start After Bytes = 200000.
    -   Start run.
    -   Observe h2 logs: "Delaying WINDOW_UPDATE..." message after ~200KB.
    -   Observe tcpdump logs: Incoming packets should stop/slow down significantly during delay.
    -   After 30s, "Resuming..." message.
    -   Verify download completes.
