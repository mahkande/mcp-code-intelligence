import importlib, importlib.util, sys

print('sys.path:')
for p in sys.path:
    print('  ', p)

names = ['python_lsp_server', 'mcp_code_intelligence.servers.python_lsp_server']
for n in names:
    try:
        m = importlib.import_module(n)
        print(f"{n} -> {getattr(m, '__file__', None)}")
    except Exception as e:
        print(f"{n} ERROR {e}")

spec = importlib.util.find_spec('mcp_code_intelligence.servers.python_lsp_server')
print('spec ->', spec)
