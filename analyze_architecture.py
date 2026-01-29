#!/usr/bin/env python3
"""Architectural Analysis Suite for MCP Code Intelligence"""

import asyncio
import sys
from pathlib import Path
from collections import defaultdict, Counter
import difflib
import hashlib
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp_code_intelligence.core.database import VectorDatabase
from mcp_code_intelligence.core.indexer import SemanticIndexer
from mcp_code_intelligence.config.settings import ProjectConfig


async def main():
    project_root = Path(__file__).parent
    src_root = project_root / "src" / "mcp_code_intelligence"

    print("=" * 80)
    print("ARCHITECTURAL X-RAY SCAN")
    print("=" * 80)

    # Initialize database
    db_path = project_root / ".mcp-code-intelligence" / "index.db"
    db = VectorDatabase(str(db_path))
    await db.initialize()

    # Initialize config
    config = ProjectConfig()

    # Initialize indexer
    indexer = SemanticIndexer(db, project_root, config)

    print("\nPHASE 1: DATA RE-INDEXING")
    print("-" * 80)
    print("Performing clean re-index of entire project...")

    # Force reindex
    indexed_count = await indexer.index_project(force_reindex=True, show_progress=False)
    print(f"[OK] Re-indexed {indexed_count} files")

    # Get statistics
    stats = await db.get_stats()
    print(f"[OK] Total chunks: {stats.total_chunks}")
    print(f"[OK] Total files: {stats.total_files}")
    print(f"[OK] Languages: {stats.languages}")

    print("\nPHASE 2: COUPLING ANALYSIS (FAN-IN/FAN-OUT)")
    print("-" * 80)

    # Analyze coupling
    all_chunks = await db.get_all_chunks()

    # Build import/dependency graph
    module_deps = defaultdict(set)
    module_usages = defaultdict(set)

    for chunk in all_chunks:
        if chunk.file_path:
            try:
                rel_path = Path(chunk.file_path).relative_to(src_root)
                module = str(rel_path).replace("\\", "/").replace(".py", "")

                if hasattr(chunk, 'docstring') and chunk.docstring:
                    content = chunk.docstring
                    if "import" in content.lower():
                        for line in content.split("\n"):
                            if "from" in line and "import" in line:
                                try:
                                    parts = line.split("import")[0].split("from")[1].strip()
                                    module_deps[module].add(parts)
                                except:
                                    pass
            except:
                pass

    # Build fan-in/fan-out metrics
    fan_in = Counter()
    fan_out = Counter()

    for module, deps in module_deps.items():
        fan_out[module] = len(deps)
        for dep in deps:
            fan_in[dep] += 1

    # Top fan-out modules
    print("\nHIGH FAN-OUT (Depends on many modules):")
    for module, count in fan_out.most_common(10):
        if count > 0:
            print(f"  {module}: {count} dependencies")

    # Top fan-in modules
    print("\nHIGH FAN-IN (Depended upon by many modules):")
    for module, count in fan_in.most_common(10):
        if count > 0:
            print(f"  {module}: used by {count} modules")

    # Check for circular dependencies
    print("\nCIRCULAR DEPENDENCY CHECK:")
    circular_deps = []
    for module1, deps1 in module_deps.items():
        for dep in deps1:
            if dep in module_deps:
                for dep2 in module_deps[dep]:
                    if dep2 == module1:
                        circular_deps.append((module1, dep))

    if circular_deps:
        print(f"  [WARN] Found {len(circular_deps)} circular dependencies:")
        for mod1, mod2 in circular_deps[:5]:
            print(f"    {mod1} <-> {mod2}")
    else:
        print("  [OK] No circular dependencies detected")

    print("\nSERVICE COUPLING ANALYSIS:")
    service_modules = [
        "services/scanner",
        "services/parser",
        "services/metrics",
    ]

    for service in service_modules:
        deps = module_deps.get(service, set())
        print(f"  {service}: {len(deps)} internal dependencies")
        if deps:
            for dep in list(deps)[:3]:
                print(f"    -> {dep}")

    print("\nPHASE 3: SEMANTIC DUPLICATION DETECTION")
    print("-" * 80)

    # Find similar chunks (code duplication)
    chunk_hashes = defaultdict(list)
    for chunk in all_chunks:
        if chunk.content:
            normalized = " ".join(chunk.content.split())
            key = hashlib.md5(normalized[:200].encode()).hexdigest()
            chunk_hashes[key].append(chunk)

    # Find duplicates
    duplicates = []
    for key, chunks in chunk_hashes.items():
        if len(chunks) > 1:
            for c1, c2 in zip(chunks[:-1], chunks[1:]):
                ratio = difflib.SequenceMatcher(None,
                    c1.content[:200] if c1.content else "",
                    c2.content[:200] if c2.content else "").ratio()
                if ratio > 0.9:
                    duplicates.append((c1, c2, ratio))

    print(f"\n[WARN] Semantic Duplications Found: {len(duplicates)}")
    if duplicates:
        for chunk1, chunk2, similarity in duplicates[:5]:
            print(f"  Similarity: {similarity:.1%}")
            print(f"    {chunk1.file_path}:{chunk1.start_line}")
            print(f"    {chunk2.file_path}:{chunk2.start_line}")

    print("\nPHASE 4: CODE MIGRATION VERIFICATION")
    print("-" * 80)

    # Check if deleted methods still exist elsewhere
    deleted_methods = [
        "_calculate_complexity",
        "_get_line_count",
        "_get_token_count",
        "_parse_source_code",
        "_extract_symbols",
        "_scan_directory",
        "_check_gitignore",
        "is_ignored"
    ]

    print("\nVerifying deleted methods don't exist elsewhere:")
    method_locations = defaultdict(list)

    for chunk in all_chunks:
        for method in deleted_methods:
            if method in (chunk.content or ""):
                method_locations[method].append(str(chunk.file_path))

    if method_locations:
        print(f"[WARN] Found {len(method_locations)} deleted methods in codebase:")
        for method, locations in method_locations.items():
            print(f"  {method}:")
            for loc in set(locations)[:3]:
                print(f"    - {loc}")
    else:
        print("[OK] All deleted methods have been properly migrated")

    # Check service implementations exist
    print("\n[OK] Verifying service implementations:")
    service_files = [
        "services/scanner.py",
        "services/parser.py",
        "services/metrics.py"
    ]

    for service_file in service_files:
        path = src_root / service_file
        if path.exists():
            lines = len(path.read_text().split("\n"))
            print(f"  [OK] {service_file}: {lines} lines")
        else:
            print(f"  [FAIL] {service_file}: MISSING")

    print("\n" + "=" * 80)
    print("ARCHITECTURAL REPORT SUMMARY")
    print("=" * 80)

    report = {
        "indexed_files": indexed_count,
        "total_chunks": stats.total_chunks,
        "total_files": stats.total_files,
        "fan_out_avg": sum(fan_out.values()) / len(fan_out) if fan_out else 0,
        "fan_in_avg": sum(fan_in.values()) / len(fan_in) if fan_in else 0,
        "circular_deps": len(circular_deps),
        "code_duplications": len(duplicates),
        "deleted_methods_found": len(method_locations),
        "services_count": len([f for f in service_files if (src_root / f).exists()])
    }

    print(f"\nMETRICS:")
    print(f"  Files indexed: {report['indexed_files']}")
    print(f"  Total code chunks: {report['total_chunks']}")
    print(f"  Avg fan-out: {report['fan_out_avg']:.1f}")
    print(f"  Avg fan-in: {report['fan_in_avg']:.1f}")
    print(f"  Circular dependencies: {report['circular_deps']}")
    print(f"  Code duplications (90%+ similar): {report['code_duplications']}")
    print(f"  Deleted methods still present: {report['deleted_methods_found']}")
    print(f"  Services implemented: {report['services_count']}/3")

    print(f"\nHEALTH STATUS:")
    if report['deleted_methods_found'] == 0:
        print("  [OK] Code migration: COMPLETE")
    else:
        print("  [WARN] Code migration: INCOMPLETE")

    if report['circular_deps'] == 0:
        print("  [OK] Architecture: CLEAN (no circular deps)")
    else:
        print(f"  [WARN] Architecture: HAS {report['circular_deps']} circular deps")

    if report['services_count'] == 3:
        print("  [OK] Services: ALL IMPLEMENTED")
    else:
        print(f"  [WARN] Services: MISSING ({3 - report['services_count']})")

    print("\nRECOMMENDATIONS FOR NEXT MODERNIZATION:")
    print("  1. Analyze search.py - likely candidate for modularization")
    print("  2. Extract database operations into separate service")
    print("  3. Review relationship.py for coupling issues")
    print("  4. Consider consolidating duplicate code patterns")

    print("\n" + "=" * 80)

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
