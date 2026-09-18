import logging

logger = logging.getLogger(__name__)


async def complexity_router(state: dict) -> dict:
    requirements_json = state.get("requirements_json", {})
    selected_patterns = state.get("selected_patterns", [])

    frs = requirements_json.get("functional_requirements", [])
    nfrs = requirements_json.get("non_functional_requirements", [])

    complexity_score = 0

    complexity_score += len(frs) * 2
    complexity_score += len(nfrs) * 3
    complexity_score += len(selected_patterns) * 5

    for fr in frs:
        content = fr.get("content", "").lower()
        if any(word in content for word in ["complex", "integration", "multiple", "distributed"]):
            complexity_score += 5
        if any(word in content for word in ["security", "auth", "encryption"]):
            complexity_score += 3

    if complexity_score < 20:
        complexity = "lightweight"
    elif complexity_score < 50:
        complexity = "standard"
    else:
        complexity = "heavyweight"

    logger.info("Complexity assessment: %s (score: %d)", complexity, complexity_score)

    return {
        "complexity": complexity,
        "current_phase": "routed",
    }


def route_by_complexity(state: dict) -> str:
    complexity = state.get("complexity", "standard")

    if complexity == "lightweight":
        return "lightweight_path"
    else:
        return "full_path"
