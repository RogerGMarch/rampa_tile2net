# Tile2Net API — just recipes
# Usage: just serve                 # start the API
#        just health                # check it's alive
#        just list-projects         # list all projects
#        just create-project        # register a city
#        just pipeline-start        # run the full pipeline
#        just polygons PROJECT=foo  # query polygons as GeoJSON

HOST      := "127.0.0.1"
PORT      := "8000"
BASE      := "http://" + HOST + ":" + PORT
PROJECT   := "valencia_center"
LOCATION  := "39.469741,-0.381756,39.478741,-0.369356"

# ── server ─────────────────────────────────────────────────────────────────────

# Start the API server on localhost:8000
serve:
    uv run python -m tile2net.api

# Start the API with hot-reload for development
dev:
    uv run uvicorn tile2net.api.main:create_app --factory --reload --host {{HOST}} --port {{PORT}}

# Open the interactive Swagger docs in a browser
docs:
    xdg-open {{BASE}}/docs 2>/dev/null || open {{BASE}}/docs 2>/dev/null || echo "Open {{BASE}}/docs"

# ── health ─────────────────────────────────────────────────────────────────────

# Check if the API is alive
health:
    curl -s {{BASE}}/ | uv run uv run python -m json.tool

# ── projects ───────────────────────────────────────────────────────────────────

# List all registered projects (optional: STATUS=completed)
list-projects STATUS="":
    @URL="{{BASE}}/projects" ; \
    [ -n "{{STATUS}}" ] && URL="$$URL?status={{STATUS}}" ; \
    curl -s "$$URL" | uv run python -m json.tool

# Get details of a specific project
get-project PROJECT=PROJECT:
    curl -s {{BASE}}/projects/{{PROJECT}} | uv run python -m json.tool

# Register a new city project
create-project PROJECT=PROJECT LOCATION=LOCATION:
    curl -s -X POST {{BASE}}/projects/ \
        -H "Content-Type: application/json" \
        -d '{"name": "{{PROJECT}}", "location": "{{LOCATION}}", "zoom": 19}' | uv run python -m json.tool

# Register Valencia Centre (Russafa area) — the default test area
create-valencia:
    curl -s -X POST {{BASE}}/projects/ \
        -H "Content-Type: application/json" \
        -d '{"name": "valencia_center", "location": "39.469,-0.382,39.479,-0.369", "zoom": 19}' | uv run python -m json.tool

# Update project fields (metric_crs, viario_type, viario_url)
patch-project PROJECT=PROJECT key="metric_crs" value="EPSG:25830":
    curl -s -X PATCH {{BASE}}/projects/{{PROJECT}} \
        -H "Content-Type: application/json" \
        -d '{"{{key}}": "{{value}}"}' | uv run python -m json.tool

# Delete a project and all its data on disk
delete-project PROJECT=PROJECT:
    curl -s -X DELETE {{BASE}}/projects/{{PROJECT}} | uv run python -m json.tool

# ── pipeline ───────────────────────────────────────────────────────────────────

# Start the full pipeline for a project (tiles → inference → postprocess → DB)
pipeline-start PROJECT=PROJECT:
    curl -s -X POST {{BASE}}/projects/{{PROJECT}}/pipeline \
        -H "Content-Type: application/json" \
        -d '{"force_reprocess": false}' | uv run python -m json.tool

# Start the pipeline skipping generate (use existing tiles)
pipeline-skip-gen PROJECT=PROJECT:
    curl -s -X POST {{BASE}}/projects/{{PROJECT}}/pipeline \
        -H "Content-Type: application/json" \
        -d '{"skip_generate": true}' | uv run python -m json.tool

# Start the pipeline skipping postprocess (generate + inference only)
pipeline-gen-inf PROJECT=PROJECT:
    curl -s -X POST {{BASE}}/projects/{{PROJECT}}/pipeline \
        -H "Content-Type: application/json" \
        -d '{"skip_postprocess": true}' | uv run python -m json.tool

# Check pipeline progress
pipeline-status PROJECT=PROJECT:
    curl -s {{BASE}}/projects/{{PROJECT}}/pipeline/status | uv run python -m json.tool

# Poll pipeline status every 3 seconds until completed/failed
pipeline-watch PROJECT=PROJECT:
    @while true; do \
        STATUS=$$(curl -s {{BASE}}/projects/{{PROJECT}}/pipeline/status | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))"); \
        echo "$$(date -u +%H:%M:%S)  status={{PROJECT}} → $$STATUS"; \
        case "$$STATUS" in completed|failed|cancelled) break ;; esac; \
        sleep 3; \
    done

# Cancel a running pipeline
pipeline-cancel PROJECT=PROJECT:
    curl -s -X DELETE {{BASE}}/projects/{{PROJECT}}/pipeline | uv run python -m json.tool

# ── data ───────────────────────────────────────────────────────────────────────

# Query polygons as GeoJSON (optional: FTYPE=sidewalk, BBOX=S,W,N,E)
polygons PROJECT=PROJECT FTYPE="" BBOX="":
    @URL="{{BASE}}/projects/{{PROJECT}}/polygons" ; \
    PARAMS="" ; \
    [ -n "{{FTYPE}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}f_type={{FTYPE}}" ; \
    [ -n "{{BBOX}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}bbox={{BBOX}}" ; \
    [ -n "$$PARAMS" ] && URL="$$URL?$$PARAMS" ; \
    curl -s "$$URL" | uv run python -m json.tool

# Query network edges as GeoJSON (optional: FTYPE, BBOX, min_width)
network PROJECT=PROJECT FTYPE="" BBOX="" min_width="":
    @URL="{{BASE}}/projects/{{PROJECT}}/network" ; \
    PARAMS="" ; \
    [ -n "{{FTYPE}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}f_type={{FTYPE}}" ; \
    [ -n "{{BBOX}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}bbox={{BBOX}}" ; \
    [ -n "{{min_width}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}min_width={{min_width}}" ; \
    [ -n "$$PARAMS" ] && URL="$$URL?$$PARAMS" ; \
    curl -s "$$URL" | uv run python -m json.tool

# Get graph summary (node/edge count, total length)
graph-summary PROJECT=PROJECT:
    curl -s {{BASE}}/projects/{{PROJECT}}/graph | uv run python -m json.tool

# Query graph edges as GeoJSON (optional: FTYPE, BBOX, min_width)
graph-edges PROJECT=PROJECT FTYPE="" BBOX="" min_width="":
    @URL="{{BASE}}/projects/{{PROJECT}}/graph/edges" ; \
    PARAMS="" ; \
    [ -n "{{FTYPE}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}f_type={{FTYPE}}" ; \
    [ -n "{{BBOX}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}bbox={{BBOX}}" ; \
    [ -n "{{min_width}}" ] && PARAMS="$${PARAMS:+$${PARAMS}&}min_width={{min_width}}" ; \
    [ -n "$$PARAMS" ] && URL="$$URL?$$PARAMS" ; \
    curl -s "$$URL" | uv run python -m json.tool

# ── shortcuts ──────────────────────────────────────────────────────────────────

# Register + pipeline in one go for the default Valencia Centre bbox
valencia-full:
    @just create-valencia && sleep 0.5 && just pipeline-start PROJECT=valencia_center

# Check everything is wired: health, list projects, a quick data query
smoke-test:
    @echo "→ health"    && just health
    @echo "→ projects"  && just list-projects
    @[ -n "$$(curl -s {{BASE}}/projects/{{PROJECT}}/polygons?limit=5 | uv run python -c 'import sys,json; print(len(json.load(sys.stdin).get(\"features\",[])))')" ] && echo "→ data OK" || echo "→ data EMPTY"

# Show this help
help:
    @just --list
