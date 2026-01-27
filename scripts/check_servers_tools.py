import importlib
from pathlib import Path
proj_root = Path(r"C:\Users\mahir\Desktop\mcp-server\mcp-vector-search")
servers_pkg = proj_root / 'src' / 'mcp_code_intelligence' / 'servers'
print('servers_dir ->', servers_pkg)
for f in sorted(servers_pkg.glob('*.py')):
    if f.name.startswith('_'):
        continue
    mod_name = f"mcp_code_intelligence.servers.{f.stem}"
    try:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, 'get_advertised_tools'):
            try:
                adv = mod.get_advertised_tools(proj_root)
                print(f.name, '->', type(adv), 'len=', None if adv is None else (len(adv) if hasattr(adv, '__len__') else 'iterable'))
            except Exception as e:
                print(f.name, 'get_advertised_tools ERROR', e)
        else:
            print(f.name, 'NO get_advertised_tools')
    except Exception as e:
        print(f.name, 'IMPORT ERROR', e)
