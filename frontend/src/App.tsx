// h2-timeout-test/frontend/src/App.tsx
import { useState, useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import './App.css';

interface RunConfig {
  host: string;
  ip: string;
  port: number;
  path: string;
  delay: number;
  start_after_bytes: number;
  ping_interval: number;
  interface: string;
}

function App() {
  const [config, setConfig] = useState<RunConfig>({
    host: 'testme2.akamaized.net',
    ip: '',
    port: 443,
    path: '/h2_timeout/h2_test.mp4',
    delay: 30,
    start_after_bytes: 200000,
    ping_interval: 2.0,
    interface: 'eth0',
  });
  
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('Ready');

  const h2TermRef = useRef<HTMLDivElement>(null);
  const tcpTermRef = useRef<HTMLDivElement>(null);
  const h2Xterm = useRef<Terminal | null>(null);
  const tcpXterm = useRef<Terminal | null>(null);

  // Initialize Terminals
  useEffect(() => {
    if (h2TermRef.current && !h2Xterm.current) {
      h2Xterm.current = new Terminal({
        rows: 20,
        cols: 80,
        theme: { background: '#1e1e1e' },
        convertEol: true
      });
      const fitAddon = new FitAddon();
      h2Xterm.current.loadAddon(fitAddon);
      h2Xterm.current.open(h2TermRef.current);
      fitAddon.fit();
    }
    
    if (tcpTermRef.current && !tcpXterm.current) {
      tcpXterm.current = new Terminal({
        rows: 20,
        cols: 80,
        theme: { background: '#000000', foreground: '#00ff00' }, // Green matrix style
        convertEol: true
      });
      const fitAddon = new FitAddon();
      tcpXterm.current.loadAddon(fitAddon);
      tcpXterm.current.open(tcpTermRef.current);
      fitAddon.fit();
    }

    return () => {
      // Cleanup? xterm dispose
    };
  }, []);

  const startRun = async () => {
    h2Xterm.current?.clear();
    tcpXterm.current?.clear();
    
    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      
      if (!res.ok) {
        const err = await res.json();
        alert(`Error: ${err.detail}`);
        return;
      }
      
      const data = await res.json();
      setRunId(data.run_id);
      setRunning(true);
      setStatus('Running...');
      
      // Connect WebSockets
      connectWebSocket('h2', h2Xterm.current);
      connectWebSocket('tcpdump', tcpXterm.current);
      
    } catch (e) {
      alert(`Network Error: ${e}`);
    }
  };

  const connectWebSocket = (type: 'h2' | 'tcpdump', term: Terminal | null) => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/${type}`);
    
    ws.onmessage = (event) => {
      term?.write(event.data); // + '\r\n' if backend doesn't send newline
    };
    
    ws.onclose = () => {
      console.log(`${type} WS closed`);
    };
  };

  const stopRun = async () => {
    try {
      await fetch('/api/stop', { method: 'POST' });
      setRunning(false);
      setStatus('Stopped');
    } catch (e) {
      console.error(e);
    }
  };

  const downloadPcap = () => {
    if (runId) {
      window.location.href = `/api/pcap?run_id=${runId}`;
    }
  };

  return (
    <div className="container">
      <header>
        <h1>HTTP/2 Flow Control Experiment</h1>
      </header>
      
      <div className="controls">
        <div className="form-group">
          <label>Host:</label>
          <input value={config.host} onChange={e => setConfig({...config, host: e.target.value})} />
        </div>
        <div className="form-group">
          <label>Target IP (Optional):</label>
          <input value={config.ip} onChange={e => setConfig({...config, ip: e.target.value})} placeholder="Auto-resolve" />
        </div>
        <div className="form-group">
            <label>Delay (sec):</label>
            <input type="number" value={config.delay} onChange={e => setConfig({...config, delay: parseFloat(e.target.value)})} />
        </div>
        <div className="form-group">
            <label>Start After (bytes):</label>
            <input type="number" value={config.start_after_bytes} onChange={e => setConfig({...config, start_after_bytes: parseInt(e.target.value)})} />
        </div>
         <div className="form-group">
            <label>Ping Interval:</label>
            <input type="number" value={config.ping_interval} onChange={e => setConfig({...config, ping_interval: parseFloat(e.target.value)})} />
        </div>
      </div>

      <div className="actions">
        {!running ? (
          <button className="btn-start" onClick={startRun}>Start Experiment</button>
        ) : (
          <button className="btn-stop" onClick={stopRun}>Stop</button>
        )}
        <span className="status">{status}</span>
        {runId && !running && (
             <button className="btn-download" onClick={downloadPcap}>Download PCAP</button>
        )}
      </div>

      <div className="terminals">
        <div className="term-pane">
          <h3>H2 Client Logs</h3>
          <div className="term-container" ref={h2TermRef}></div>
        </div>
        <div className="term-pane">
          <h3>tcpdump Output</h3>
          <div className="term-container" ref={tcpTermRef}></div>
        </div>
      </div>
    </div>
  );
}

export default App;
