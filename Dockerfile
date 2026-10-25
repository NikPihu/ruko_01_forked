# The red team / blue team console (red_team_blue_team/blue_team/webapp.py), for hosting (render.yaml).
# The Bedrock key is never in the image: set AWS_BEARER_TOKEN_BEDROCK as a secret on the host.
# Without it the agents run offline (deterministic drafts) and the console still works.
FROM python:3.12-slim

# libgomp1: LightGBM needs OpenMP at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
COPY ml/requirements.txt ml/requirements.txt
COPY red_team_blue_team/blue_team/requirements.txt red_team_blue_team/blue_team/requirements.txt
RUN pip install --no-cache-dir -r red_team_blue_team/blue_team/requirements.txt

COPY . .

ENV PYTHONPATH=/app/backend:/app/ml:/app/data:/app/red_team_blue_team:/app/synthetic_playbook \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0

# The seed 21 breach world the console's runs start from (README: about 2 + 5 minutes). Built into the
# image so the console has data the moment it starts; generated files are git-ignored in the repo.
RUN python -m blue_team.testworld --out data/sim_v2_out/breach \
 && python -m dataset.replay --data data/sim_v2_out/breach --out ml/data/tables/breach.parquet --warmup-days 7

EXPOSE 8765
CMD ["sh", "-c", "python -m blue_team app --port ${PORT:-8765}"]
