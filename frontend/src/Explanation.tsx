// h2-timeout-test/frontend/src/Explanation.tsx
import React from 'react';

const Explanation: React.FC = () => {
  return (
    <div className="explanation">
      <h2>Understanding H2 & TCP Flow Control</h2>
      
      <p>
        Flow control is essential for preventing a fast sender from overwhelming a slow receiver. 
        In HTTP/2, there are two layers of flow control happening simultaneously:
      </p>

      <h3>1. TCP Flow Control (Layer 4)</h3>
      <p>
        TCP manages buffer space at the OS kernel level. If the application (our Python script) 
        stops reading from the socket (<code>sock.recv()</code>), the OS kernel's Receive Buffer fills up.
      </p>
      <div className="diagram">
{`Client OS (Kernel)                      Server OS (Kernel)
+-------------------+                   +-------------------+
| TCP Recv Buffer   | <---(Data)------- | TCP Send Buffer   |
| [||||||||||     ] |                   | [Data....]        |
+-------------------+                   +-------------------+
          |                                      ^
    (Window Update)                        (Stops Sending)
          |                                      |
          +-----(Window Size = 0) ----------------+
`}
      </div>
      <p>
        <strong>Result:</strong> The server's OS stops sending TCP packets. The server application 
        may block on <code>write()</code>. This usually leads to a <em>long</em> timeout (TCP Keep-Alive) 
        rather than an immediate HTTP/2 error.
      </p>

      <h3>2. HTTP/2 Flow Control (Layer 7)</h3>
      <p>
        HTTP/2 adds its own flow control on top of TCP. This is managed by <code>WINDOW_UPDATE</code> frames.
        Even if the TCP buffer is empty (socket is being read), the application must explicitly tell 
        the peer "I have processed X bytes, you can send more".
      </p>
      <div className="diagram">
{`Client App (Python)                     Server App (Nginx/Akamai)
+-------------------+                   +-------------------+
| H2 Window State   |                   | H2 Window State   |
| [Current: 0     ] |                   | [Remaining: 0   ] |
+-------------------+                   +-------------------+
          |                                      ^
    (WINDOW_UPDATE)                        (Stops Stream)
          |                                      |
          +-----(Frame Type=8) ------------------+
`}
      </div>
      <p>
        <strong>Our Test Scenario (Delay Mode):</strong>
        <br/>
        We <em>continue</em> reading from the TCP socket (keeping TCP window open), but we 
        <strong>withhold</strong> the HTTP/2 <code>WINDOW_UPDATE</code> frame.
        <br/><br/>
        <strong>Result:</strong> The server sees the TCP connection is healthy, but the H2 stream is stalled. 
        Most servers have an <strong>H2 Idle Timeout</strong> (e.g., 10-30s) for this state and will close 
        the connection with a <code>GOAWAY</code> (Error Code 0 or 2) to free up resources.
      </p>

      <h3>Log Format Reference</h3>
      <table className="log-format-table">
        <thead>
          <tr>
            <th>Tag</th>
            <th>Description</th>
            <th>Example</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>CONN</code></td>
            <td>TCP/TLS Connection details</td>
            <td><code>tcp_connected peer=1.2.3.4:443</code></td>
          </tr>
          <tr>
            <td><code>H2</code></td>
            <td>Protocol events (Headers, Settings)</td>
            <td><code>request_sent stream_id=1</code></td>
          </tr>
          <tr>
            <td><code>DATA</code></td>
            <td>Data frames & Window status</td>
            <td><code>data sz=16384 stream_window=0</code></td>
          </tr>
          <tr>
            <td><code>STATE</code></td>
            <td>Internal test state</td>
            <td><code>delay_started withhold_seconds=30.0</code></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
};

export default Explanation;
