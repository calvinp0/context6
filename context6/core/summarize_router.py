from __future__ import annotations

from typing import Any

from context6.core.ollama_summarizer import summarize_entity as summarize_entity_ollama
from context6.core.codex_summarizer import summmarize_entity_codex

def summarize_entity_routed(kind: str,
    fqname: str,
    signature: str,
    docstring: str,
    code: str,
    mode: str = "auto",          # "auto" | "ollama" | "codex"
    codex_bin: str = "codex",
) -> dict[str, Any]:
    """
    A function to summarize a code entity, routing between different summarization backends based on the specified mode and the characteristics of the input. 
    The function supports an "auto" mode that tries Ollama first and falls back to Codex if the result is truncated, 
        as well as explicit "ollama" and "codex" modes for direct control over the summarization backend.
    
    :param kind: The kind of code entity being summarized (e.g., "class", "function", "method")
    :type kind: str
    :param fqname: The fully qualified name of the code entity (e.g., "module.Class.method")
    :type fqname: str
    :param signature: The signature of the code entity (e.g., function parameters)
    :type signature: str
    :param docstring: The docstring associated with the code entity, providing documentation and context
    :type docstring: str
    :param code: The code snippet of the entity to be summarized, which may be truncated if it exceeds certain length limits for the summarization backend
    :type code: str
    :param mode: The summarization mode to use, which can be "auto" (try Ollama and fall back to Codex if truncated), "ollama" (use Ollama directly), or "codex" (use Codex directly)
    :type mode: str
    :param codex_bin: The path to the Codex binary, used when the mode is set to "codex" or when falling back to Codex in "auto" mode
    :type codex_bin: str
    :return: A dictionary containing the summary of the code entity, along with metadata about the summarization process such as whether truncation occurred, the approximate token count, coverage level, and which backend was used for summarization 
    :rtype: dict[str, Any]
    """

    mode = (mode or "auto").lower().strip()
    if mode not in ("auto", "ollama", "codex"):
        raise ValueError(f"Invalid mode: {mode}")
    
    if mode == "codex":
        res = summmarize_entity_codex(kind, fqname, signature, docstring, code, codex_bin=codex_bin)
        res["backend"] = "codex"
        return res
    elif mode == "ollama":
        res = summarize_entity_ollama(kind, fqname, signature, docstring, code, stream=False)
        res["backend"] = "ollam"
        return res
    

    res = summarize_entity_ollama(kind, fqname, signature, docstring, code)
    if res.get("was_truncated"):
        res = summmarize_entity_codex(kind, fqname, signature, docstring, code, codex_bin=codex_bin)
        res["backend"] = "codex"
        return res
    res["backend"] = "ollam"
    
    return res
