import { useState, useRef, useEffect } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'
import './App.css'

interface Config {
  host: string;
  ip: string;
  port: number;
  path: string;
  delay: number;
  start_after_bytes: number;
  ping_interval: number;
}

function App() {
  const [config, setConfig] = useState<Config>({
    host: 'testme2.akamaized.net',
    ip: '',
    port: 443,
    path: '/h2_timeout/h2_test.mp4',
    delay: 30,
    start_after_bytes: 10000,
    ping_interval: 0
  })
  
  const [running, setRunning] = useState(false)
  
  // Terminal refs
  const h2TermRef = useRef<HTMLDivElement>(null)
  const h2Xterm = useRef<Terminal | null>(null)
  
  // WebSocket refs
  const wsH2 = useRef<WebSocket | null>(null)

  useEffect(() => {
    // Initialize Terminals
    if (h2TermRef.current && !h2Xterm.current) {
      h2Xterm.current = new Terminal({
        cursorBlink: true,
        fontFamily: 'Consolas, monospace',
        fontSize: 12,
        fontWeight: 'normal',
        theme: {
          background: '#000000',
          foreground: '#cccccc'
        },
        convertEol: true, // Handle \n as \r\n
      })
      const fitAddon = new FitAddon()
      h2Xterm.current.loadAddon(fitAddon)
      h2Xterm.current.open(h2TermRef.current)
      fitAddon.fit()
    }
    
    // Cleanup
    return () => {
      wsH2.current?.close()
    }
  }, [])

  const connectWebSockets = () => {
    // Close existing
    wsH2.current?.close()
    
    // H2 Log WebSocket
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsBase = `${proto}//${window.location.host}`; 
    
    wsH2.current = new WebSocket(`${wsBase}${import.meta.env.BASE_URL}ws/h2`)
    wsH2.current.onmessage = (event) => {
      const msg = event.data.replace(/\n/g, '\r\n');
      h2Xterm.current?.write(msg) 
    }
  }

  const handleStart = async () => {
    h2Xterm.current?.clear()
    setRunning(true)
    
    try {
      const payload = { ...config, interface: 'any' }
      
      const res = await fetch(`${import.meta.env.BASE_URL}api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      
      if (!res.ok) throw new Error(await res.text())
      
      // Connect WS immediately after start
      setTimeout(connectWebSockets, 500)
      
    } catch (e: any) {
      alert(`Error starting: ${e.message}`)
      setRunning(false)
    }
  }

  const handleStop = async () => {
    try {
      await fetch(`${import.meta.env.BASE_URL}api/stop`, { method: 'POST' })
      setRunning(false)
      wsH2.current?.close()
    } catch (e) {
      console.error(e)
    }
  }
  
  return (
    <div className="container">
      <header>
        <h1>H2 Flow Control Timeout Test</h1>
      </header>
      
      <div className="controls">
        <div className="form-group">
          <label>Host (SNI)</label>
          <input 
            value={config.host} 
            onChange={e => setConfig({...config, host: e.target.value})} 
          />
        </div>
        <div className="form-group">
          <label>Target IP (Optional)</label>
          <input 
            value={config.ip} 
            onChange={e => setConfig({...config, ip: e.target.value})} 
            placeholder="e.g., 1.2.3.4"
          />
        </div>
        <div className="form-group">
          <label>Port</label>
          <input 
            type="number"
            value={config.port} 
            onChange={e => setConfig({...config, port: parseInt(e.target.value)})} 
          />
        </div>
        <div className="form-group">
          <label>Path</label>
          <input 
            value={config.path} 
            onChange={e => setConfig({...config, path: e.target.value})} 
          />
        </div>
        <div className="form-group">
          <label>Start Delay After (Bytes)</label>
          <input 
            type="number"
            value={config.start_after_bytes} 
            onChange={e => setConfig({...config, start_after_bytes: parseInt(e.target.value)})} 
          />
        </div>
        <div className="form-group">
          <label>Delay Duration (Sec)</label>
          <input 
            type="number"
            value={config.delay} 
            onChange={e => setConfig({...config, delay: parseFloat(e.target.value)})} 
          />
        </div>
         <div className="form-group">
          <label>Ping Interval (Sec, 0=Off)</label>
          <input 
            type="number"
            value={config.ping_interval} 
            onChange={e => setConfig({...config, ping_interval: parseFloat(e.target.value)})} 
          />
        </div>
      </div>
      
      <div className="actions">
        {!running ? (
          <button className="btn-start" onClick={handleStart}>Start Experiment</button>
        ) : (
          <button className="btn-stop" onClick={handleStop}>Stop</button>
        )}
        
        <span className="status">Status: {running ? "RUNNING" : "IDLE"}</span>
      </div>
      
      <div className="terminals">
        <div className="term-pane">
          <h3>H2 Client Logs</h3>
          <div className="term-container" ref={h2TermRef}></div>
        </div>
      </div>
      
      <div className="explanation">
          <h2>How HTTP/2 Connections Work (Simplified)</h2>

          <h3>1. Initial Connection (TCP + TLS + H2 Negotiation)</h3>
          <div className="diagram">
{`CLIENT                        SERVER
  |                             |
  |---[TCP SYN]---------------->|  (1) TCP 3-Way Handshake
  |<--[TCP SYN-ACK]-------------|
  |---[TCP ACK]---------------->|  TCP Connected!
  |                             |
  |---[ClientHello + SNI]------>|  (2) TLS Handshake Starts
  |   (SNI: testme2.akamaized.net) "I want to talk to THIS domain"
  |   (ALPN: h2, http/1.1)         "I prefer HTTP/2"
  |                             |
  |<--[ServerHello + Cert]------|  Server picks cert for SNI domain
  |   (ALPN: h2 selected)       |  Server confirms HTTP/2 usage
  |                             |
  |---[ClientKeyExchange]------>|  (3) Secure Channel Established
  |                             |
  |---[H2 Connection Preface]-->|  (4) HTTP/2 Starts
  |---[SETTINGS Frame]--------->|
  |<--[SETTINGS Frame]----------|
  |                             |
  |---[HEADERS Stream 1]------->|  (5) Client Requests File (GET /path)
  |                             |
`}
          </div>

          <h3>2. Understanding Flow Control (Why we test this)</h3>
          <p>
            <strong>SNI (Server Name Indication):</strong> Allows the server to host multiple domains on one IP. 
            The client tells the server <em>before</em> the handshake completes which domain it wants, 
            so the server can send the correct SSL Certificate.
          </p>

          <h4>Normal Flow (Both Happy)</h4>
          <div className="diagram">
{`CLIENT                        SERVER
  |                             |
  |<--[DATA Stream 1 (16KB)]----|  Server sends data chunk
  |---[TCP ACK]---------------->|  OS says "Packet received"
  |                             |
  |---[WINDOW_UPDATE (16KB)]--->|  App says "I processed 16KB, send more!"
  |                             |
  |<--[DATA Stream 1 (16KB)]----|  Server sees open window -> Sends next chunk
`}
          </div>
          
          <h4>The Test Scenario (H2 Application Stall)</h4>
          <p>This tool simulates a client application that is <strong>stuck or busy</strong>.</p>
          <div className="diagram">
{`CLIENT                        SERVER
  |                             |
  |<--[DATA Stream 1 (16KB)]----|  Server sends data chunk
  |---[TCP ACK]---------------->|  OS says "Packet received" (TCP OK)
  |                             |
  |      (NO WINDOW UPDATE)     |  <-- APP LAYER STALL (Simulated Delay)
  |                             |
  |                             |  Server H2 Window for Stream 1 = 0
  |      ... Waiting ...        |  Server TCP Window = OPEN
  |                             |
  |<--[GOAWAY Error]------------|  Server: "You are not reading! Timeout!"
  |      (Connection Closed)    |
`}
          </div>

          <h3>3. Test Parameters Guide</h3>
          <table className="log-format-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Description</th>
                <th>How it affects the test</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Start Delay After (Bytes)</strong></td>
                <td>Threshold of received data before triggering the stall.</td>
                <td>Simulates an app that works fine at first (e.g., loads header) but hangs on large body download.</td>
              </tr>
              <tr>
                <td><strong>Delay Duration (Sec)</strong></td>
                <td>How long to withhold the <code>WINDOW_UPDATE</code> frame.</td>
                <td>If this duration exceeds the server's <strong>H2 Idle Timeout</strong>, the server will kill the connection.</td>
              </tr>
              <tr>
                <td><strong>Ping Interval (Sec)</strong></td>
                <td>Sends an H2 <code>PING</code> frame periodically.</td>
                <td>Keeps the connection alive (heartbeat). Useful to check if the server is still responsive during a stall.</td>
              </tr>
            </tbody>
          </table>
      </div>
      
    </div>
  )
}

export default App
