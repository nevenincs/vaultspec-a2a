import json

from lib.api.app import create_app


app = create_app()
openapi_schema = app.openapi()

with open("openapi.json", "w") as f:
    json.dump(openapi_schema, f, indent=2)
