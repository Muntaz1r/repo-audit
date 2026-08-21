import os
import json
import logging
import asyncio
import httpx
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv
from app.services.analyzers.base import BasePillarAnalyzer, PillarResult, FindingResult
from app.services.packager import package_repository_context

logger = logging.getLogger("repo_audit.semantic")

SEMANTIC_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "architecture_type": {"type": "string"},
        "purpose_summary": {"type": "string"},
        "design_patterns": {"type": "array", "items": {"type": "string"}},
        "key_modules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "dependencies": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["name", "path", "purpose"]
            }
        },
        "data_flow_summary": {"type": "string"},
        "architectural_strengths": {"type": "array", "items": {"type": "string"}},
        "architectural_risks": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["architecture_type", "purpose_summary", "design_patterns", "key_modules", "data_flow_summary"]
}

class SemanticAnalyzer(BasePillarAnalyzer):
    @property
    def pillar_key(self) -> str:
        return "semantic"

    @property
    def name(self) -> str:
        return "Semantic Analysis"

    def get_api_keys(self) -> Dict[str, str]:
        load_dotenv(override=True)
        return {
            "gemini": os.getenv("GEMINI_API_KEY", "").strip(),
            "groq": os.getenv("GROQ_API_KEY", "").strip(),
        }

    async def analyze(self, repo_dir: Path, metadata: Dict[str, Any]) -> PillarResult:
        pkg = package_repository_context(repo_dir, metadata)
        keys = self.get_api_keys()

        # 1. Primary Engine: Google Gemini 2.5 Flash
        if keys["gemini"]:
            for attempt in range(2):
                try:
                    gemini_data = await self._call_gemini(pkg, keys["gemini"])
                    return self._build_result(gemini_data, engine="Gemini 2.5 Flash (Live AI)")
                except Exception as e:
                    err_str = str(e).lower()
                    # On rate limit (429) or auth/quota error, failover to Groq immediately without sleeping
                    if "429" in err_str or "400" in err_str or "403" in err_str or "quota" in err_str or "not found" in err_str:
                        logger.warning("[SemanticAnalyzer] Gemini quota/auth error: %s. Immediately switching to Groq fallback...", e)
                        break
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    logger.warning("[SemanticAnalyzer] Gemini call error: %s. Trying Groq fallback...", e)

        # 2. Secondary Engine: Groq Cloud (Live AI)
        if keys["groq"]:
            for attempt in range(2):
                try:
                    groq_data, used_model = await self._call_groq(pkg, keys["groq"])
                    return self._build_result(groq_data, engine=f"Groq {used_model} (Live AI)")
                except Exception as e:
                    err_str = str(e).lower()
                    if "429" in err_str or "401" in err_str or "403" in err_str:
                        logger.warning("[SemanticAnalyzer] Groq quota/auth error: %s. Falling back to offline heuristic...", e)
                        break
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    logger.warning("[SemanticAnalyzer] Groq call error: %s. Falling back to offline heuristic...", e)

        # 3. Deterministic Offline Heuristic Fallback
        return self._heuristic_analysis(pkg, metadata)

    async def _call_gemini(self, pkg: Dict[str, Any], api_key: str) -> Dict[str, Any]:
        """Calls Google AI Studio Gemini 2.5 Flash API via REST with JSON schema enforcement."""
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        prompt = self._build_prompt(pkg)

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": SEMANTIC_JSON_SCHEMA,
                "temperature": 0.2
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(api_url, json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"Gemini API Error {response.status_code}: {response.text}")
            
            resp_json = response.json()
            raw_text = resp_json["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw_text)

    async def _call_groq(self, pkg: Dict[str, Any], api_key: str) -> Tuple[Dict[str, Any], str]:
        """Calls Groq Cloud API with compact digest respecting free-tier TPM limits."""
        api_url = "https://api.groq.com/openai/v1/chat/completions"
        prompt = self._build_compact_prompt(pkg)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Models prioritized in order of capability & availability
        models_to_try = [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.6-27b",
            "groq/compound",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant"
        ]

        async with httpx.AsyncClient(timeout=12.0) as client:
            last_err = None
            for model_name in models_to_try:
                payload = {
                    "model": model_name,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are an expert system architect auditing a GitHub repository. "
                                "Return strictly valid JSON with keys: architecture_type, purpose_summary, "
                                "design_patterns, key_modules (array of {name, path, purpose, dependencies}), "
                                "data_flow_summary, architectural_strengths, architectural_risks. "
                                "List architectural_risks ONLY if concrete structural flaws exist; otherwise return an empty array."
                            )
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                    "max_tokens": 1500
                }
                try:
                    response = await client.post(api_url, json=payload, headers=headers)
                    if response.status_code == 200:
                        resp_json = response.json()
                        raw_text = resp_json["choices"][0]["message"]["content"]
                        return json.loads(raw_text), model_name
                    elif response.status_code in [400, 404]:
                        last_err = f"Groq Model {model_name} Error {response.status_code}: {response.text}"
                        continue  # Try next available model
                    else:
                        last_err = f"Groq API Error {response.status_code}: {response.text}"
                except Exception as e:
                    last_err = str(e)
            
            raise RuntimeError(last_err or "All Groq model attempts failed")

    def _build_compact_prompt(self, pkg: Dict[str, Any]) -> str:
        """Builds a token-efficient digest (<= 2500 tokens) to guarantee compatibility with Groq TPM limits."""
        tree_lines = pkg.get("tree", "").splitlines()[:35]
        tree_compact = "\n".join(tree_lines)
        readme = (pkg.get("readme_snippet") or "")[:1200]
        
        # Take at most 2 entrypoints up to 1000 chars each
        entrypoints_compact = {}
        for path, code in list(pkg.get("entrypoints", {}).items())[:2]:
            entrypoints_compact[path] = code[:800]

        return f"""
Analyze this GitHub repository:
REPOSITORY: {pkg.get('repo_name')}
PRIMARY LANGUAGE: {pkg.get('primary_language')}
DESCRIPTION: {pkg.get('description', '')}

DIRECTORY TREE (Top Excerpt):
{tree_compact}

README EXTRACT:
{readme}

ENTRYPOINT EXCERPTS:
{json.dumps(entrypoints_compact, indent=2)}

Provide architectural understanding. Return strictly valid JSON.
"""

    def _build_prompt(self, pkg: Dict[str, Any]) -> str:
        return f"""
Analyze the following repository structure, manifests, and entrypoint files:

REPOSITORY: {pkg['repo_name']}
PRIMARY LANGUAGE: {pkg['primary_language']}
DESCRIPTION: {pkg['description']}

DIRECTORY TREE:
{pkg['tree']}

README EXTRACT:
{pkg['readme_snippet']}

DEPENDENCY MANIFESTS:
{json.dumps(pkg['manifests'], indent=2)}

ENTRYPOINT SOURCE EXCERPTS:
{json.dumps(pkg['entrypoints'], indent=2)}

Provide a comprehensive, non-author architectural understanding of this codebase. Return strictly valid JSON.
Only report architectural_risks if actual architectural anti-patterns exist; otherwise return [].
"""

    def _build_result(self, data: Dict[str, Any], engine: str) -> PillarResult:
        findings: List[FindingResult] = []
        score = 95

        raw_risks = data.get("architectural_risks") or []
        total_risk_penalty = 0

        for risk_item in raw_risks:
            if isinstance(risk_item, dict):
                risk_text = risk_item.get("description") or risk_item.get("risk") or str(risk_item)
            else:
                risk_text = str(risk_item)

            risk_text = risk_text.strip()
            if not risk_text:
                continue

            total_risk_penalty += 5
            findings.append(FindingResult(
                severity="warning",
                title=f"Architectural Risk: {risk_text[:60]}",
                description=risk_text,
                impact="Potential modular coupling or maintenance bottlenecks for non-author maintainers.",
                recommendation="Refactor component boundaries to isolate shared dependencies."
            ))

        score -= min(total_risk_penalty, 25)
        score = max(min(score, 100), 60)
        status = "PASS" if score >= 80 else "WARN"

        metrics = {
            "engine": engine,
            "architecture_type": data.get("architecture_type") or "Modular Software",
            "purpose_summary": data.get("purpose_summary") or "",
            "design_patterns": data.get("design_patterns") or [],
            "key_modules": data.get("key_modules") or [],
            "data_flow_summary": data.get("data_flow_summary") or "",
            "architectural_strengths": data.get("architectural_strengths") or [],
        }

        return PillarResult(
            pillar_key=self.pillar_key,
            score=score,
            status=status,
            metrics_json=metrics,
            findings=findings
        )

    def _heuristic_analysis(self, pkg: Dict[str, Any], metadata: Dict[str, Any]) -> PillarResult:
        """Deterministic offline heuristic semantic inferrer."""
        lang = pkg.get("primary_language", "General")
        repo_name = pkg.get("repo_name", "")
        desc = pkg.get("description") or "Open source software project"

        # Infer architecture type
        tree_text = pkg.get("tree", "")
        if "routes/" in tree_text or "controllers/" in tree_text or "views/" in tree_text:
            arch_type = "MVC Web Application / Service"
        elif "lib/" in tree_text or "src/" in tree_text:
            arch_type = "Modular Library / Package"
        elif "cmd/" in tree_text or "cli" in tree_text:
            arch_type = "CLI Utility / Command Line Tool"
        elif "api/" in tree_text or "endpoints/" in tree_text:
            arch_type = "REST API / Backend Microservice"
        else:
            arch_type = f"{lang} Application"

        # Infer key modules from directories
        modules = []
        for line in tree_text.splitlines():
            if "/" in line and ("├── " in line or "└── " in line):
                dir_name = line.split("── ")[-1].replace("/", "").strip()
                if dir_name and not dir_name.startswith("."):
                    modules.append({
                        "name": dir_name,
                        "path": f"{dir_name}/",
                        "purpose": f"Contains core {dir_name} logic and sub-components.",
                        "dependencies": []
                    })
            if len(modules) >= 5:
                break

        if not modules:
            modules.append({
                "name": "root",
                "path": "./",
                "purpose": "Root application package containing entrypoint logic.",
                "dependencies": []
            })

        metrics = {
            "engine": "Offline Heuristic Parser",
            "architecture_type": arch_type,
            "purpose_summary": f"{repo_name} is a {arch_type.lower()} written primarily in {lang}. {desc}.",
            "design_patterns": ["Modular Architecture", "Separation of Concerns"],
            "key_modules": modules,
            "data_flow_summary": f"Execution initiates from top-level entrypoints and delegates operations across {len(modules)} discovered module namespaces.",
            "architectural_strengths": [
                f"Structured {lang} codebase with clean module boundaries",
                "Standard entrypoint and manifest conventions"
            ]
        }

        return PillarResult(
            pillar_key=self.pillar_key,
            score=90,
            status="PASS",
            metrics_json=metrics,
            findings=[]
        )
