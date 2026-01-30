import subprocess
import json
import time
import os

def test_mcp_startup_details():
    env = os.environ.copy()
    env["PYTHONPATH"] = "c:/Users/mahir/Desktop/mcp-server/mcp-vector-search/src"
    env["MCP_PROJECT_ROOT"] = "C:/Users/mahir/Desktop/orm-drf"
    
    cmd = [
        r"C:\Users\mahir\AppData\Local\Programs\Python\Python312\python.exe",
        "-m", "mcp_code_intelligence.mcp"
    ]
    
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True
    )
    
    time.sleep(10)
    
    # Send initialize request
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        }
    }
    
    process.stdin.write(json.dumps(init_request) + "\n")
    process.stdin.flush()
    
    time.sleep(5)
    
    # Read anything available
    stdout = ""
    while True:
        line = process.stdout.readline()
        if not line: break
        stdout += line
        if "result" in line: break
        
    process.terminate()
    _, stderr = process.communicate()
    
    print("--- STDOUT ---")
    print(stdout)
    print("--- STDERR ---")
    print(stderr)

if __name__ == "__main__":
    test_mcp_startup_details()
