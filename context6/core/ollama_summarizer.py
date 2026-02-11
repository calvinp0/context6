from __future__ import annotations
import os
import json
import urllib.request
from typing import Any, Dict

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("CONTEXT6_MODEL", "qwen2.5:7b")
MAX_CHARS = 25000
NUM_CTX = int(os.getenv("CONTEXT6_NUM_CTX", "6144"))
OUT_TOKENS = 220
SAFETY = 600
BUDGET_TOKENS = max(512, NUM_CTX - OUT_TOKENS - SAFETY)
BUDGET_CHARS = BUDGET_TOKENS * 4


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    """
    Send a POST request with a JSON payload and return the JSON response.
    
    :param url: The URL to send the POST request to
    :type url: str
    :param payload: Payload to send in the POST request
    :type payload: Dict[str, Any]
    :param timeout: Timeout in seconds for the request (default: 120)
    :type timeout: int
    :return: The JSON response as a dictionary
    :rtype: dict[str, Any]
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))

def _post_json_stream(url: str, payload: Dict[str, Any], timeout: int = 120) -> str:
    """
    Send a POST request with a JSON payload and return the streamed JSON response as a string.
    
    :param url: The URL to send the POST request to
    :type url: str
    :param payload: Payload to send in the POST request
    :type payload: Dict[str, Any]
    :param timeout: Timeout in seconds for the request (default: 120)
    :type timeout: int
    :return: The streamed JSON response as a string
    :rtype: str
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method="POST")
    out_parts = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            obj = json.loads(raw.decode("utf-8"))
            if "response" in obj:
                out_parts.append(obj["response"])
                # tiny heartbeat
                print(".", end="", flush=True)
            if obj.get("done"):
                break
    print("")  # newline after dots
    return "".join(out_parts).strip()


def summarize_entity(kind: str, fqname: str, signature: str, docstring: str, code: str, stream: bool = True) -> dict[str, Any]:
    """
    Summarize a code entity using Ollama.

    Provided is the system prompt, the user prompt (with entity info and code), and the model generates a structured summary.
    The function handles truncation of code to fit within Ollama's context window and enforces a final "Coverage" line based on whether truncation occurred.


    :param kind: The kind of the entity (e.g., "function", "class")
    :type kind: str
    :param fqname: The fully qualified name of the entity
    :type fqname: str
    :param signature: The signature of the entity (e.g., function parameters)
    :type signature: str
    :param docstring: The docstring of the entity
    :type docstring: str
    :param code: The code snippet of the entity
    :type code: str
    :param stream: Whether to use streaming response from Ollama (default: True)
    :type stream: bool
    :return: A dictionary containing the summary and metadata about the summarization process
    :rtype: dict[str, Any]
    """

    system = (
        "You are summarizing Python code for a local developer knowledge base.\n"
        "Rules:\n"
        "- Be factual; if unclear, write 'unclear'.\n"
        "- No speculation.\n"
        "- Keep it compact.\n"
        "- Output MUST be at most 12 lines.\n"
    )

    was_truncated = len(code) > MAX_CHARS
    code = code[:MAX_CHARS]

    template = (
        "Produce a 12-lines-or-less structured summary with these headings:\n"
        "1) Purpose:\n"
        "2) Responsibilities:\n"
        "3) Inputs/Outputs:\n"
        "4) Side effects:\n"
        "5) Error modes:\n"
        "6) Key methods/flows:\n"
        "7) Extension points:\n"
        "8) Related concepts:\n"
        "(Skip headings that are not applicable, but still stay <=12 lines.)\n"
        "Last line MUST be: Coverage: full|partial|unclear\n"
    )

    base_user = (
        f"ENTITY\nkind: {kind}\nfqname: {fqname}\nsignature: {signature}\n\n"
        f"DOCSTRING (may be empty)\n{docstring}\n\n"
        f"CODE\n\n"
        f"{template}"
    )
    overhead_chars = len(system) + 2 + len(base_user)

    max_code_chars = max(2000, BUDGET_CHARS - overhead_chars)

    was_truncated = len(code) > max_code_chars
    code = code[:max_code_chars]


    user = (
        f"ENTITY\nkind: {kind}\nfqname: {fqname}\nsignature: {signature}\n\n"
        f"NOTE\ncode_truncated: {was_truncated}\nmax_chars: {MAX_CHARS}\n\n"
        f"DOCSTRING (may be empty)\n{docstring}\n\n"
        f"CODE\n{code}\n\n"
        f"{template}"
    )

    prompt_text = system + "\n\n" + user
    prompt_chars = len(prompt_text)
    approx_tokens = prompt_chars // 4


    payload = {
        "model": MODEL,
        "prompt": user,
        "system": system,
        "stream": stream,
        "options": {
            "temperature": 0.2,
            "num_predict": 180,
            "num_ctx": NUM_CTX,
        },
    }

    url = f"{OLLAMA_HOST}/api/generate"

    if stream:
        text = _post_json_stream(url, payload)
    else:
        out = _post_json(url, payload)
        text = (out.get("response") or "")

    text = text.strip()
    lines = text.splitlines()

    forced_coverage = "partial" if was_truncated else "full"

    if lines and lines[-1].startswith("Coverage:"):
        lines[-1] = f"Coverage: {forced_coverage}"
    else:
        lines.append(f"Coverage: {forced_coverage}")

    text = "\n".join(lines)


    coverage = "unclear"
    last = text.splitlines()[-1].strip() if text else ""
    if last.startswith("Coverage:"):
        coverage = last.split(":", 1)[1].strip()

    return {
        "summary": text,
        "was_truncated": was_truncated,
        "approx_tokens": approx_tokens,
        "prompt_chars": prompt_chars,
        "coverage": coverage,
    }
