import os, json
import boto3
from botocore.exceptions import BotoCoreError, ClientError


def get_client():
    """Create a Bedrock runtime client using the default AWS SDK configuration."""
    return boto3.client("bedrock-runtime")


def invoke(prompt: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
    """Send *prompt* to the Bedrock model identified by ``BEDROCK_MODEL_ID``.
    Returns the raw completion string (expected to be a YAML document).
    """
    model_id = os.getenv("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError("BEDROCK_MODEL_ID environment variable is not set")
    client = get_client()
    payload = {
        "prompt": prompt,
        "maxTokens": max_tokens,
        "temperature": temperature,
        "stopSequences": ["\n---\n"],
    }
    try:
        response = client.invoke_model(
            body=json.dumps(payload).encode("utf-8"),
            modelId=model_id,
            contentType="application/json",
        )
        raw = response["body"].read().decode("utf-8")
        result = json.loads(raw)
        return result.get("completion", "")
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Bedrock invocation failed: {e}")
