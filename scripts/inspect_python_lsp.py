import importlib
from pathlib import Path
m = importlib.import_module('mcp_code_intelligence.servers.python_lsp_server')
print('MODULE_FILE ->', getattr(m,'__file__',None))
print('DIR ->', [n for n in dir(m) if not n.startswith('_')])
print('get_advertised_tools:', getattr(m,'get_advertised_tools',None))
try:
    res = m.get_advertised_tools(Path(r"C:\Users\mahir\Desktop\mcp-server\mcp-vector-search"))
    print('CALL_RESULT_TYPE ->', type(res), 'len ->', None if res is None else (len(res) if hasattr(res,'__len__') else 'iter'))
except Exception as e:
    import traceback
    traceback.print_exc()
    print('CALL ERROR ->', e)
