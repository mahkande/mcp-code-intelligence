"""MCP server implementation with service-oriented architecture."""

import asyncio
import os
import sys
import json
from pathlib import Path
from typing import Any

from loguru import logger
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ServerCapabilities,
    TextContent,
    Tool,
)

from ..analysis import (
    ProjectMetrics,
    SmellDetector,
    SmellSeverity,
)
from ..config.thresholds import ThresholdConfig
from ..core.exceptions import ProjectNotFoundError
from ..core.project import ProjectManager
from ..core.lsp_proxy import get_manager, stop_proxies
from ..core import formatters
from ..parsers.registry import ParserRegistry

# Import new services
from .services import SessionService, RoutingService, ProtocolService


class MCPVectorSearchServer:
    """MCP server for vector search - service-oriented architecture."""

    def __init__(
        self,
        project_root: Path | None = None,
        enable_file_watching: bool | None = None,
    ):
        """Initialize MCP server with auto-detection and service wiring.

        Args:
            project_root: Project root directory (auto-detected if None)
            enable_file_watching: Enable file watching (from env var if None)
        """
        # --- Startup logging: env keys and interpreter ---
        from mcp_vector_search.logger_config import logger
        critical_envs = [k for k in os.environ if any(x in k for x in ["JINA", "OPENAI", "MCP", "API_KEY", "TOKEN"])]
        masked = {k: (v[:2] + "****" if v else "****") for k, v in os.environ.items() if k in critical_envs}
        logger.info(f"[Startup] Kritik env anahtarları: {masked}")
        logger.info(f"[Startup] Aktif Python: {sys.executable}")

        # Auto-detect project root
        if project_root is None:
            env_project_root = os.getenv("MCP_PROJECT_ROOT") or os.getenv("PROJECT_ROOT")
            if env_project_root:
                project_root = Path(env_project_root).resolve()
                logger.info(f"Using project root from environment: {project_root}")
            else:
                project_root = Path.cwd()
                logger.info(f"Using current directory as project root: {project_root}")

        self.project_root = project_root
        self.project_manager = ProjectManager(self.project_root)

        # Determine file watching setting
        if enable_file_watching is None:
            env_value = os.getenv("MCP_ENABLE_FILE_WATCHING", "true").lower()
            enable_file_watching = env_value in ("true", "1", "yes", "on")

        # Wire services
        self.session_service = SessionService(project_root, enable_file_watching)
        self.routing_service = RoutingService()
        self.protocol_service = ProtocolService()

        # Register tool handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register all tool handlers with routing service."""
        handlers = {
            "search_code": self._search_code,
            "search_similar": self._search_similar,
            "search_context": self._search_context,
            "get_project_status": self._get_project_status,
            "index_project": self._index_project,
            "analyze_project": self._analyze_project,
            "analyze_file": self._analyze_file,
            "find_smells": self._find_smells,
            "get_complexity_hotspots": self._get_complexity_hotspots,
            "check_circular_dependencies": self._check_circular_dependencies,
            "find_symbol": self._find_symbol,
            "get_relationships": self._get_relationships,
            "interpret_analysis": self._interpret_analysis,
            "find_duplicates": self._find_duplicates,
            "silence_health_issue": self._silence_health_issue,
            "propose_logic": self._handle_propose_logic,
            "impact_analysis": self._impact_analysis,
        }
        for tool_name, handler in handlers.items():
            self.routing_service.register_handler(tool_name, handler)

    async def _impact_analysis(self, args: dict[str, Any]) -> CallToolResult:
        """Handle impact_analysis tool call."""
        symbol_name = args.get("symbol_name", "")
        max_depth = args.get("max_depth", 5)
        if not symbol_name:
            return self.protocol_service.build_error_response("symbol_name parameter is required")
        try:
            from ..core.relationships import analyze_impact
            result = analyze_impact(self.project_root, symbol_name, max_depth)
            if "error" in result:
                return self.protocol_service.build_error_response(result["error"])
            response_lines = [f"# Impact Analysis for '{symbol_name}'\n"]
            response_lines.append(f"**Origin:** {result['origin']}")
            response_lines.append(f"**Complexity Score:** {result['complexity_score']}")
            response_lines.append("\n## Immediate Impact (Directly Affected Files):")
            if result["immediate_impact"]:
                for f in result["immediate_impact"]:
                    response_lines.append(f"- {f}")
            else:
                response_lines.append("- None")
            response_lines.append("\n## Deep Impact (Transitive):")
            if result["deep_impact"]:
                for f in result["deep_impact"]:
                    response_lines.append(f"- {f}")
            else:
                response_lines.append("- None")
            return self.protocol_service.build_text_response("\n".join(response_lines))
        except Exception as e:
            logger.error(f"Impact analysis failed: {e}")
            return self.protocol_service.build_error_response(f"Impact analysis failed: {str(e)}")

    def get_tools(self) -> list[Tool]:
        """Get available MCP tools via central registry."""
        try:
            from ..core.tool_registry import get_mcp_tools

            servers_tools: dict = {}
            try:
                from ..servers.filesystem_server import FilesystemServer
                fs = FilesystemServer(self.project_root)
                servers_tools["filesystem"] = [
                    {"name": t.name, "description": t.description, "inputSchema": getattr(t, "inputSchema", {})}
                    for t in fs.advertised_tools()
                ]
            except Exception:
                pass

            try:
                from ..servers.python_lsp_server import PythonLSPServer
                py = PythonLSPServer(self.project_root)
                servers_tools["python_lsp"] = [
                    {"name": t.name, "description": t.description, "inputSchema": getattr(t, "inputSchema", {})}
                    for t in py.advertised_tools()
                ]
            except Exception:
                pass

            if servers_tools:
                return get_mcp_tools(self.project_root, servers_tools=servers_tools)

            return get_mcp_tools(self.project_root)
        except Exception:
            return []

    def get_capabilities(self) -> ServerCapabilities:
        """Get server capabilities."""
        return ServerCapabilities(tools={"listChanged": True}, logging={})

    # ========== Proxy Properties to SessionService ==========

    @property
    def _initialized(self) -> bool:
        """Check if session is initialized."""
        return self.session_service._initialized

    @property
    def search_engine(self):
        """Get search engine from session service."""
        return self.session_service.search_engine

    async def initialize(self) -> None:
        """Initialize server and session."""
        await self.session_service.initialize()

    async def call_tool(self, request: CallToolRequest) -> CallToolResult:
        """Handle tool calls via routing service."""
        # Initialize session if needed
        if request.params.name != "interpret_analysis" and not self.session_service.is_initialized:
            await self.session_service.initialize()

        try:
            # Route to appropriate handler
            result = await self.routing_service.route_tool_call(request)

            # Inject Guardian health notice if enabled
            if self.session_service._enable_guardian and not result.isError and request.params.name in ("search_code", "search_similar", "get_project_status"):
                try:
                    health_notice = await self.session_service.guardian.get_health_notice()
                    if health_notice:
                        notice_content = TextContent(type="text", text=health_notice + "\n\n---\n")
                        result.content.insert(0, notice_content)
                except Exception as g_err:
                    logger.debug(f"Guardian check failed: {g_err}")

            return result

        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            return self.protocol_service.build_error_response(f"Tool execution failed: {str(e)}")

    async def cleanup(self) -> None:
        """Cleanup resources through session service."""
        await self.session_service.cleanup()

    # ========== Tool Handlers ==========

    async def _search_code(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_code tool call."""
        query = args.get("query", "")
        limit = args.get("limit", 10)
        similarity_threshold = args.get("similarity_threshold", 0.3)

        if not query:
            return self.protocol_service.build_error_response("Query parameter is required")

        if not self.session_service.search_engine:
            return self.protocol_service.build_error_response("Search engine not initialized")

        filters = self.protocol_service.build_search_filters(args)

        try:
            results = await self.session_service.search_engine.search(
                query=query,
                limit=limit,
                similarity_threshold=similarity_threshold,
                filters=filters,
            )

            if not results:
                return self.protocol_service.build_text_response(f"No results found for query: '{query}'")

            response_lines = [f"Found {len(results)} results for query: '{query}'\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend(self.protocol_service.format_search_result(result, i))

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return self.protocol_service.build_error_response(f"Search failed: {str(e)}")

    async def _search_similar(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_similar tool call."""
        file_path_str = args.get("file_path", "")
        if not file_path_str:
            return self.protocol_service.build_error_response("file_path parameter is required")

        file_path = self.protocol_service.resolve_file_path(file_path_str, self.project_root)
        if not file_path:
            return self.protocol_service.build_error_response(f"File not found: {file_path_str}")

        try:
            results = await self.session_service.search_engine.search_similar(
                file_path=file_path,
                function_name=args.get("function_name"),
                limit=args.get("limit", 10),
                similarity_threshold=args.get("similarity_threshold", 0.3),
            )

            if not results:
                return self.protocol_service.build_text_response(f"No similar code found for {file_path_str}")

            response_lines = [f"Found {len(results)} similar code snippets for {file_path_str}\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend(self.protocol_service.format_search_result(result, i))

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Similar search failed: {e}")
            return self.protocol_service.build_error_response(f"Similar search failed: {str(e)}")

    async def _search_context(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_context tool call."""
        description = args.get("description", "")
        if not description:
            return self.protocol_service.build_error_response("description parameter is required")

        try:
            results = await self.session_service.search_engine.search_by_context(
                context_description=description,
                focus_areas=args.get("focus_areas"),
                limit=args.get("limit", 10)
            )

            if not results:
                return self.protocol_service.build_text_response(f"No contextually relevant code found for: {description}")

            response_lines = [f"Found {len(results)} contextually relevant code snippets for: {description}\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend(self.protocol_service.format_search_result(result, i))

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Context search failed: {e}")
            return self.protocol_service.build_error_response(f"Context search failed: {str(e)}")

    async def _get_project_status(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_project_status tool call."""
        try:
            config = self.project_manager.load_config()

            if self.session_service.search_engine:
                stats = await self.session_service.database.get_stats()
                status_info = {
                    "project_root": str(config.project_root),
                    "index_path": str(config.index_path),
                    "file_extensions": config.file_extensions,
                    "embedding_model": config.embedding_model,
                    "languages": config.languages,
                    "total_chunks": stats.total_chunks,
                    "total_files": stats.total_files,
                    "index_size": f"{stats.index_size_mb:.2f} MB" if hasattr(stats, "index_size_mb") else "Unknown",
                }
            else:
                status_info = {
                    "project_root": str(config.project_root),
                    "index_path": str(config.index_path),
                    "file_extensions": config.file_extensions,
                    "embedding_model": config.embedding_model,
                    "languages": config.languages,
                    "status": "Not indexed",
                }

            response_text = "# Project Status\n\n"
            response_text += f"**Project Root:** {status_info['project_root']}\n"
            response_text += f"**Index Path:** {status_info['index_path']}\n"
            response_text += f"**File Extensions:** {', '.join(status_info['file_extensions'])}\n"
            response_text += f"**Embedding Model:** {status_info['embedding_model']}\n"
            response_text += f"**Languages:** {', '.join(status_info['languages'])}\n"

            if "total_chunks" in status_info:
                response_text += f"**Total Chunks:** {status_info['total_chunks']}\n"
                response_text += f"**Total Files:** {status_info['total_files']}\n"
                response_text += f"**Index Size:** {status_info['index_size']}\n"
            else:
                response_text += f"**Status:** {status_info['status']}\n"

            return self.protocol_service.build_text_response(response_text)

        except ProjectNotFoundError:
            return self.protocol_service.build_error_response(f"Project not initialized at {self.project_root}")
        except Exception as e:
            logger.error(f"Project status failed: {e}")
            return self.protocol_service.build_error_response(f"Project status failed: {str(e)}")

    async def _index_project(self, args: dict[str, Any]) -> CallToolResult:
        """Handle index_project tool call."""
        try:
            from ..cli.commands.index_runner import run_indexing

            await run_indexing(
                project_root=self.project_root,
                force_reindex=args.get("force", False),
                extensions=args.get("file_extensions"),
                show_progress=False,
                workers=args.get("workers"),
                throttle=args.get("throttle"),
                max_size=args.get("max_size"),
                important_only=args.get("important_only"),
            )

            await self.cleanup()
            await self.session_service.initialize()

            return self.protocol_service.build_text_response("Project indexing completed successfully!")

        except Exception as e:
            logger.error(f"Indexing failed: {e}")
            return self.protocol_service.build_error_response(f"Indexing failed: {str(e)}")

    async def _find_symbol(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_symbol tool call."""
        name = args.get("name", "")
        if not name:
            return self.protocol_service.build_error_response("Name parameter is required")

        if not self.session_service.search_engine:
            return self.protocol_service.build_error_response("Search engine not initialized")

        try:
            results = await self.session_service.search_engine.find_symbol(name, args.get("symbol_type"))

            if not results:
                return self.protocol_service.build_text_response(f"Symbol '{name}' not found.")

            response_lines = [f"Found {len(results)} definitions for '{name}':\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend([
                    f"## Definition {i}",
                    f"File: {result.file_path}",
                    f"Lines: {result.start_line}-{result.end_line}",
                    f"Type: {result.chunk_type}",
                ])
                if result.class_name:
                    response_lines.append(f"Class: {result.class_name}")
                response_lines.extend(["\n```\n" + result.content + "\n```\n"])

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Find symbol failed: {e}")
            return self.protocol_service.build_error_response(f"Find symbol failed: {str(e)}")

    async def _get_relationships(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_relationships tool call."""
        name = args.get("name", "")
        if not name:
            return self.protocol_service.build_error_response("Name parameter is required")

        if not self.session_service.search_engine:
            return self.protocol_service.build_error_response("Search engine not initialized")

        try:
            data = await self.session_service.search_engine.get_symbol_relationships(name)

            if "error" in data:
                return self.protocol_service.build_text_response(data["error"])

            response_lines = [f"# Relationships for '{name}'\n"]

            def_info = data["definition"]
            response_lines.extend([
                "## Definition",
                f"- **File:** {def_info['file']}",
                f"- **Lines:** {def_info['lines']}",
                f"- **Type:** {def_info['type']}\n",
                "## Callers (Who calls this?)",
            ])

            if not data["callers"]:
                response_lines.append("- No external callers found.")
            else:
                for caller in data["callers"]:
                    response_lines.append(f"- `{caller['name']}` ({caller['file']})")

            response_lines.extend([
                "",
                "## Callees (What does this call?)",
            ])

            if not data["callees"]:
                response_lines.append("- No internal calls found.")
            else:
                for callee in data["callees"]:
                    response_lines.append(f"- `{callee['name']}` ({callee['file']})")

            response_lines.extend([
                "",
                "## Semantic Siblings (Conceptually similar)",
            ])

            if not data["semantic_siblings"]:
                response_lines.append("- No similar patterns found.")
            else:
                for sibling in data["semantic_siblings"]:
                    response_lines.append(f"- `{sibling['name']}` ({sibling['file']}) [Score: {sibling['similarity']}]")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Get relationships failed: {e}")
            return self.protocol_service.build_error_response(f"Get relationships failed: {str(e)}")

    async def _analyze_project(self, args: dict[str, Any]) -> CallToolResult:
        """Handle analyze_project tool call."""
        threshold_preset = args.get("threshold_preset", "standard")
        output_format = args.get("output_format", "summary")

        try:
            from ..cli.commands.analyze import _analyze_file, _find_analyzable_files
            from ..analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )

            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            if not files_to_analyze:
                return self.protocol_service.build_error_response("No analyzable files found in project")

            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            project_metrics = ProjectMetrics(project_root=str(self.project_root))

            for file_path in files_to_analyze:
                try:
                    file_metrics = await _analyze_file(file_path, parser_registry, collectors)
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception:
                    continue

            project_metrics.compute_aggregates()

            smell_detector = SmellDetector()
            all_smells = []
            for file_path, file_metrics in project_metrics.files.items():
                file_smells = smell_detector.detect_all(file_metrics, file_path)
                all_smells.extend(file_smells)

            if output_format == "detailed":
                output = project_metrics.to_summary()
                output["smells"] = {
                    "total": len(all_smells),
                    "by_severity": {
                        "error": sum(1 for s in all_smells if s.severity == SmellSeverity.ERROR),
                        "warning": sum(1 for s in all_smells if s.severity == SmellSeverity.WARNING),
                        "info": sum(1 for s in all_smells if s.severity == SmellSeverity.INFO),
                    },
                }
                response_text = json.dumps(output, indent=2)
            else:
                summary = project_metrics.to_summary()
                response_lines = [
                    "# Project Analysis Summary\n",
                    f"**Project Root:** {summary['project_root']}",
                    f"**Total Files:** {summary['total_files']}",
                    f"**Total Functions:** {summary['total_functions']}",
                    f"**Total Classes:** {summary['total_classes']}",
                    f"**Average File Complexity:** {summary['avg_file_complexity']}\n",
                    "## Complexity Distribution",
                ]

                dist = summary["complexity_distribution"]
                for grade in ["A", "B", "C", "D", "F"]:
                    response_lines.append(f"- Grade {grade}: {dist[grade]} chunks")

                response_lines.extend([
                    "\n## Health Metrics",
                    f"- Average Health Score: {summary['health_metrics']['avg_health_score']:.2f}",
                    f"- Files Needing Attention: {summary['health_metrics']['files_needing_attention']}",
                    "\n## Code Smells",
                    f"- Total: {len(all_smells)}",
                    f"- Errors: {sum(1 for s in all_smells if s.severity == SmellSeverity.ERROR)}",
                    f"- Warnings: {sum(1 for s in all_smells if s.severity == SmellSeverity.WARNING)}",
                    f"- Info: {sum(1 for s in all_smells if s.severity == SmellSeverity.INFO)}",
                ])

                response_text = "\n".join(response_lines)

            return self.protocol_service.build_text_response(response_text)

        except Exception as e:
            logger.error(f"Project analysis failed: {e}")
            return self.protocol_service.build_error_response(f"Project analysis failed: {str(e)}")

    async def _analyze_file(self, args: dict[str, Any]) -> CallToolResult:
        """Handle analyze_file tool call."""
        file_path_str = args.get("file_path", "")
        if not file_path_str:
            return self.protocol_service.build_error_response("file_path parameter is required")

        file_path = self.protocol_service.resolve_file_path(file_path_str, self.project_root)
        if not file_path:
            return self.protocol_service.build_error_response(f"File not found: {file_path_str}")

        try:
            from ..cli.commands.analyze import _analyze_file
            from ..analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )

            parser_registry = ParserRegistry()
            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            file_metrics = await _analyze_file(file_path, parser_registry, collectors)

            if not file_metrics:
                return self.protocol_service.build_error_response(f"Unable to analyze file: {file_path_str}")

            smell_detector = SmellDetector()
            smells = smell_detector.detect_all(file_metrics, str(file_path))

            response_lines = [
                f"# File Analysis: {file_path.name}\n",
                f"**Path:** {file_path}",
                f"**Total Lines:** {file_metrics.total_lines}",
                f"**Code Lines:** {file_metrics.code_lines}",
                f"**Comment Lines:** {file_metrics.comment_lines}",
                f"**Functions:** {file_metrics.function_count}",
                f"**Classes:** {file_metrics.class_count}",
                f"**Methods:** {file_metrics.method_count}\n",
                "## Complexity Metrics",
                f"- Total Complexity: {file_metrics.total_complexity}",
                f"- Average Complexity: {file_metrics.avg_complexity:.2f}",
                f"- Max Complexity: {file_metrics.max_complexity}",
                f"- Health Score: {file_metrics.health_score:.2f}\n",
            ]

            if smells:
                response_lines.append(f"## Code Smells ({len(smells)})\n")
                for smell in smells[:10]:
                    response_lines.append(f"- [{smell.severity.value.upper()}] {smell.name}: {smell.description}")
                if len(smells) > 10:
                    response_lines.append(f"\n... and {len(smells) - 10} more")
            else:
                response_lines.append("## Code Smells\n- None detected")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"File analysis failed: {e}")
            return self.protocol_service.build_error_response(f"File analysis failed: {str(e)}")

    async def _find_smells(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_smells tool call."""
        from ..cli.commands.analyze import _analyze_file, _find_analyzable_files
        from ..analysis import (
            CognitiveComplexityCollector,
            CyclomaticComplexityCollector,
            MethodCountCollector,
            NestingDepthCollector,
            ParameterCountCollector,
        )

        try:
            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            project_metrics = ProjectMetrics(project_root=str(self.project_root))

            for file_path in files_to_analyze:
                try:
                    file_metrics = await _analyze_file(file_path, parser_registry, collectors)
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception:
                    continue

            smell_detector = SmellDetector()
            all_smells = []
            for file_path, file_metrics in project_metrics.files.items():
                file_smells = smell_detector.detect_all(file_metrics, file_path)
                all_smells.extend(file_smells)

            smell_type_filter = args.get("smell_type")
            severity_filter = args.get("severity")

            filtered_smells = all_smells

            if smell_type_filter:
                filtered_smells = [s for s in filtered_smells if s.name == smell_type_filter]

            if severity_filter:
                severity_enum = SmellSeverity(severity_filter)
                filtered_smells = [s for s in filtered_smells if s.severity == severity_enum]

            if not filtered_smells:
                return self.protocol_service.build_text_response("No code smells found")

            response_lines = [f"# Code Smells Found: {len(filtered_smells)}\n"]

            by_severity = {
                "error": [s for s in filtered_smells if s.severity == SmellSeverity.ERROR],
                "warning": [s for s in filtered_smells if s.severity == SmellSeverity.WARNING],
                "info": [s for s in filtered_smells if s.severity == SmellSeverity.INFO],
            }

            for severity_level in ["error", "warning", "info"]:
                smells = by_severity[severity_level]
                if smells:
                    response_lines.append(f"## {severity_level.upper()} ({len(smells)})\n")
                    for smell in smells[:20]:
                        response_lines.append(f"- **{smell.name}** at `{smell.location}`")
                        response_lines.append(f"  {smell.description}")
                        if smell.suggestion:
                            response_lines.append(f"  *Suggestion: {smell.suggestion}*")
                        response_lines.append("")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Smell detection failed: {e}")
            return self.protocol_service.build_error_response(f"Smell detection failed: {str(e)}")

    async def _get_complexity_hotspots(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_complexity_hotspots tool call."""
        from ..cli.commands.analyze import _analyze_file, _find_analyzable_files
        from ..analysis import (
            CognitiveComplexityCollector,
            CyclomaticComplexityCollector,
            MethodCountCollector,
            NestingDepthCollector,
            ParameterCountCollector,
        )

        try:
            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            project_metrics = ProjectMetrics(project_root=str(self.project_root))

            for file_path in files_to_analyze:
                try:
                    file_metrics = await _analyze_file(file_path, parser_registry, collectors)
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception:
                    continue

            hotspots = project_metrics.get_hotspots(limit=args.get("limit", 10))

            if not hotspots:
                return self.protocol_service.build_text_response("No complexity hotspots found")

            response_lines = [f"# Top {len(hotspots)} Complexity Hotspots\n"]

            for i, file_metrics in enumerate(hotspots, 1):
                response_lines.extend([
                    f"## {i}. {Path(file_metrics.file_path).name}",
                    f"**Path:** `{file_metrics.file_path}`",
                    f"**Average Complexity:** {file_metrics.avg_complexity:.2f}",
                    f"**Max Complexity:** {file_metrics.max_complexity}",
                    f"**Total Complexity:** {file_metrics.total_complexity}",
                    f"**Functions:** {file_metrics.function_count}",
                    f"**Health Score:** {file_metrics.health_score:.2f}\n",
                ])

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Hotspot detection failed: {e}")
            return self.protocol_service.build_error_response(f"Hotspot detection failed: {str(e)}")

    async def _check_circular_dependencies(self, args: dict[str, Any]) -> CallToolResult:
        """Handle check_circular_dependencies tool call."""
        from ..cli.commands.analyze import _find_analyzable_files
        from ..analysis.collectors.coupling import build_import_graph

        try:
            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            if not files_to_analyze:
                return self.protocol_service.build_error_response("No analyzable files found in project")

            import_graph = build_import_graph(self.project_root, files_to_analyze, language="python")

            forward_graph: dict[str, list[str]] = {}

            for file_path in files_to_analyze:
                file_str = str(file_path.relative_to(self.project_root))
                if file_str not in forward_graph:
                    forward_graph[file_str] = []

                for module, importers in import_graph.items():
                    for importer in importers:
                        importer_str = str(
                            Path(importer).relative_to(self.project_root)
                            if Path(importer).is_absolute()
                            else importer
                        )
                        if importer_str == file_str:
                            if module not in forward_graph[file_str]:
                                forward_graph[file_str].append(module)

            def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
                """Find all cycles in import graph using DFS."""
                cycles = []
                visited = set()
                rec_stack = set()

                def dfs(node: str, path: list[str]) -> None:
                    visited.add(node)
                    rec_stack.add(node)
                    path.append(node)

                    for neighbor in graph.get(node, []):
                        if neighbor not in visited:
                            dfs(neighbor, path.copy())
                        elif neighbor in rec_stack:
                            try:
                                cycle_start = path.index(neighbor)
                                cycle = path[cycle_start:] + [neighbor]
                                cycle_tuple = tuple(sorted(cycle))
                                if not any(tuple(sorted(c)) == cycle_tuple for c in cycles):
                                    cycles.append(cycle)
                            except ValueError:
                                pass

                    rec_stack.remove(node)

                for node in graph:
                    if node not in visited:
                        dfs(node, [])

                return cycles

            cycles = find_cycles(forward_graph)

            if not cycles:
                return self.protocol_service.build_text_response("No circular dependencies detected")

            response_lines = [f"# Circular Dependencies Found: {len(cycles)}\n"]

            for i, cycle in enumerate(cycles, 1):
                response_lines.append(f"## Cycle {i}")
                response_lines.append("```")
                for j, node in enumerate(cycle):
                    if j < len(cycle) - 1:
                        response_lines.extend([f"{node}", "  ↓"])
                    else:
                        response_lines.append(f"{node} (back to {cycle[0]})")
                response_lines.append("```\n")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Circular dependency check failed: {e}")
            return self.protocol_service.build_error_response(f"Circular dependency check failed: {str(e)}")

    async def _interpret_analysis(self, args: dict[str, Any]) -> CallToolResult:
        """Handle interpret_analysis tool call."""
        analysis_json_str = args.get("analysis_json", "")
        if not analysis_json_str:
            return self.protocol_service.build_error_response("analysis_json parameter is required")

        try:
            from ..analysis.interpretation import AnalysisInterpreter, LLMContextExport

            analysis_data = self.protocol_service.parse_json_safely(analysis_json_str)
            if not analysis_data:
                return self.protocol_service.build_error_response("Invalid JSON input")

            export = LLMContextExport(**analysis_data)
            interpreter = AnalysisInterpreter()
            interpretation = interpreter.interpret(
                export,
                focus=args.get("focus", "summary"),
                verbosity=args.get("verbosity", "normal")
            )

            return self.protocol_service.build_text_response(interpretation)

        except Exception as e:
            logger.error(f"Analysis interpretation failed: {e}")
            return self.protocol_service.build_error_response(f"Interpretation failed: {str(e)}")

    async def _find_duplicates(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_duplicates tool call."""
        try:
            from .duplicates_tool import handle_find_duplicates
            return await handle_find_duplicates(self.session_service.search_engine, args)
        except Exception as e:
            logger.error(f"Find duplicates failed: {e}")
            return self.protocol_service.build_error_response(f"Find duplicates failed: {str(e)}")

    async def _silence_health_issue(self, args: dict[str, Any]) -> CallToolResult:
        """Handle silence_health_issue tool call."""
        issue_id = args.get("issue_id")
        try:
            success = await self.session_service.guardian.silence_issue(issue_id)
            if success:
                msg = f"✅ Issue '{issue_id}' has been silenced. It will no longer appear in Guardian notices."
            else:
                msg = f"ℹ️ Issue '{issue_id}' was already silenced or could not be found."
            return self.protocol_service.build_text_response(msg)
        except Exception as e:
            logger.error(f"Silence health issue failed: {e}")
            return self.protocol_service.build_error_response(f"Silence health issue failed: {str(e)}")

    async def _handle_propose_logic(self, args: dict[str, Any]) -> CallToolResult:
        """Handle propose_logic tool call."""
        if not self.session_service._enable_logic_check:
            return self.protocol_service.build_text_response(
                "ℹ️ Logic Check feature is currently disabled in project configuration."
            )

        intent = args.get("intent", "")
        if not intent:
            return self.protocol_service.build_error_response("Intent is required.")

        try:
            analysis = await self.session_service.guardian.check_intent_duplication(intent, args.get("code_draft"))

            if not analysis["duplicate_found"]:
                return self.protocol_service.build_text_response(
                    "✅ No similar logic found. You can proceed with the implementation."
                )

            response_lines = [
                "### 🛑 STOP! LOGIC DUPLICATION DETECTED",
                "\n> [!CAUTION]",
                "> **Highly similar logic already exists in your codebase.**",
                "> Implementing this again would create technical debt. Please use the existing implementation below:\n"
            ]

            for i, match in enumerate(analysis["matches"], 1):
                func = match['function_name'] or "Global/Block"
                response_lines.extend([
                    f"#### 🔍 Match {i} (Confidence: {match['score']:.2f})",
                    f"- **File:** `{match['file_path']}`",
                    f"- **Symbol:** `{func}`",
                    f"- **Location:** `{match['location']}`",
                    "\n**Existing Code Snippet:**",
                    f"```python\n{match['content'][:400]}...\n```\n",
                ])

            response_lines.extend([
                "\n---",
                "> [!TIP]",
                "> Instead of writing new code, please **import and reuse** the existing logic.",
            ])

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Propose logic failed: {e}")
            return self.protocol_service.build_error_response(f"Propose logic failed: {str(e)}")


def create_mcp_server(
    project_root: Path | None = None, enable_file_watching: bool | None = None
) -> Server:
    """Create and configure the MCP server."""
    server = Server("mcp-code-intelligence")
    mcp_server = MCPVectorSearchServer(project_root, enable_file_watching)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools."""
        return mcp_server.get_tools()

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None):
        """Handle tool calls."""
        from types import SimpleNamespace

        mock_request = SimpleNamespace()
        mock_request.params = SimpleNamespace()
        mock_request.params.name = name
        mock_request.params.arguments = arguments or {}

        result = await mcp_server.call_tool(mock_request)
        return result.content

    server._mcp_server = mcp_server
    return server


async def run_mcp_server(
    project_root: Path | None = None, enable_file_watching: bool | None = None
) -> None:
    """Run the MCP server using stdio transport."""
    server = create_mcp_server(project_root, enable_file_watching)

    init_options = InitializationOptions(
        server_name="mcp-code-intelligence",
        server_version="0.4.0",
        capabilities=ServerCapabilities(tools={"listChanged": True}, logging={}),
    )

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"MCP server error: {e}")
        raise
    finally:
        if hasattr(server, "_mcp_server"):
            logger.info("Performing server cleanup...")
            await server._mcp_server.cleanup()


if __name__ == "__main__":
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    enable_file_watching = None
    if "--no-watch" in sys.argv:
        enable_file_watching = False
        sys.argv.remove("--no-watch")
    elif "--watch" in sys.argv:
        enable_file_watching = True
        sys.argv.remove("--watch")

    asyncio.run(run_mcp_server(project_root, enable_file_watching))
