import asyncio
from fastmcp import Client

async def main():
    client = Client("/home/calvin/code/context6/context6/mcp/context6_server.py")


    async with client:
        tools = await client.list_tools()
        print("Available tools:", tools)

if __name__ == "__main__":
    asyncio.run(main())