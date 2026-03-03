import json

from pydantic import TypeAdapter

from lib.api.app import create_app
from lib.api.schemas.commands import ClientMessage
from lib.api.schemas.events import ServerEvent


app = create_app()
openapi_schema = app.openapi()

# Generate the JSON schemas using the correct ref template for OpenAPI
ta_server = TypeAdapter(ServerEvent)
ta_client = TypeAdapter(ClientMessage)

server_schema = ta_server.json_schema(ref_template="#/components/schemas/{model}")
client_schema = ta_client.json_schema(ref_template="#/components/schemas/{model}")

if "components" not in openapi_schema:
    openapi_schema["components"] = {"schemas": {}}
elif "schemas" not in openapi_schema["components"]:
    openapi_schema["components"]["schemas"] = {}

schemas = openapi_schema["components"]["schemas"]

if "$defs" in server_schema:
    for name, schema in server_schema.pop("$defs").items():
        schemas[name] = schema

if "$defs" in client_schema:
    for name, schema in client_schema.pop("$defs").items():
        schemas[name] = schema

schemas["ServerEvent"] = server_schema
schemas["ClientMessage"] = client_schema

with open("openapi.json", "w") as f:
    json.dump(openapi_schema, f, indent=2)
