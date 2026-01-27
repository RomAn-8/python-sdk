"""MCPServer quickstart example.

Run from the repository root:
    uv run mcp-server-demo/mcpserver_quickstart.py
"""

from mcp.server.mcpserver import MCPServer

# Create an MCP server
mcp = MCPServer("Demo")


# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


# Add a weather tool (demo)
@mcp.tool()
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get weather for a city."""
    # This would normally call a weather API
    return f"Weather in {city}: 22degrees{unit[0].upper()}"


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"


# Add a prompt
@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt"""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }

    return f"{styles.get(style, styles['friendly'])} for someone named {name}."


# Run with streamable HTTP transport
if __name__ == "__main__":
    # If you connect from a browser-based client (like MCP Inspector in "Direct" mode),
    # you must enable CORS and expose the Mcp-Session-Id header.
    from starlette.middleware.cors import CORSMiddleware

    import uvicorn

    # IMPORTANT: Do not mount the returned app into another Starlette app.
    # The Streamable HTTP transport relies on the Starlette lifespan to run
    # its internal session manager (task group). If you mount it, the mounted
    # app's lifespan won't run and you'll get:
    # "Task group is not initialized. Make sure to use run()."
    #
    # Endpoint will be available at http://127.0.0.1:8000/mcp
    app = mcp.streamable_http_app(json_response=True)

    app = CORSMiddleware(
        app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        expose_headers=["Mcp-Session-Id"],
    )

    uvicorn.run(app, host="127.0.0.1", port=8000)